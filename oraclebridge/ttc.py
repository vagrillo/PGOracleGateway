"""Macchina a stati TTC del proxy OracleBridge.

Decodifica le richieste del client python-oracledb thin e costruisce le
risposte nel formato atteso (message stream chiuso da messaggio ERROR(4)
con codice 0/ORA-xxxxx o STATUS(9)); i risultati delle query viaggiano come
DESCRIBE_INFO(16) + ROW_HEADER(6) + ROW_DATA(7); i bind OUT PL/SQL come
IO_VECTOR(11) + ROW_DATA.

Note di protocollo verificate sui sorgenti python-oracledb thin:
- il rowcount DML viaggia nel campo esteso del messaggio ERROR(4) con
  numero errore 0 (stesso messaggio che porta il cursor id assegnato);
- la fine delle righe e' segnalata con ERROR 1403 (ORA-01403), che il
  client assorbe quando si trova in fase di fetch;
- al primo execute di una query il client chiede DEFINE (describe) e poi
  rifà la richiesta completa: la risposta describe termina con ERROR(0).
"""
import re

from .auth import AuthState, decrypt_password, derive_combo_key
from .buffer import TTCReader, TTCWriter
from .errors import OrabridgeError, ora_message
from .translate import (PlsqlBlock, find_bind_names,
                        replace_bind_placeholders, translate_sql)
from .types import (ORA_TYPE_CHAR, ORA_TYPE_CURSOR, ORA_TYPE_DATE,
                    ORA_TYPE_INTERVAL_DS, ORA_TYPE_LONG, ORA_TYPE_NUMBER,
                    ORA_TYPE_RAW, ORA_TYPE_TIMESTAMP, ORA_TYPE_TIMESTAMP_TZ,
                    ORA_TYPE_VARCHAR, decode_date, decode_interval_ds,
                    decode_number, decode_timestamp, encode_column_value)

# TTC function codes
FUNC_AUTH_1 = 118
FUNC_AUTH_2 = 115
FUNC_EXECUTE = 94
FUNC_REEXECUTE = 4
FUNC_REEXECUTE_FETCH = 78
FUNC_FETCH = 5
FUNC_COMMIT = 14
FUNC_ROLLBACK = 15
FUNC_LOGOFF = 9
FUNC_PING = 147

# TTC message types
MSG_ERROR = 4
MSG_ROW_HEADER = 6
MSG_ROW_DATA = 7
MSG_STATUS = 9
MSG_IO_VECTOR = 11
MSG_DESCRIBE_INFO = 16
MSG_PIGGYBACK = 17

EXEC_EXECUTE = 0x20
EXEC_FETCH = 0x40

BIND_DIR_INOUT = 48

SERVER_VERSION_NUM = (23 << 24) | (26 << 16) | (3 << 12)   # 23.26.3.0.0
PROTOCOL_BANNER = "OracleBridge Proxy (compatibile Oracle 26ai)"


class BindParam:
    __slots__ = ("name", "ora_type", "value")

    def __init__(self):
        self.name = "?"
        self.ora_type = ORA_TYPE_VARCHAR
        self.value = None


class Session:
    """Stato TTC di una connessione client."""

    def __init__(self, pg_host: str, pg_port: int, pg_db: str, log=None):
        self.pg_host = pg_host
        self.pg_port = pg_port
        self.pg_db = pg_db
        self.log = log
        self.auth = AuthState()
        self.pg = None                    # PgSession, creata in fase auth
        self.known_password = None        # dal config (opzionale)
        self.user = None
        self.ref_cursors: dict[int, dict] = {}
        self.next_ref_id = 1

    def _dbg(self, *args):
        if self.log:
            self.log(*args)

    # ==================================================================
    # Dispatch
    # ==================================================================
    def handle_ttc(self, payload: bytes) -> bytes:
        self._dbg("ttc:", payload[:24].hex())
        rdr = TTCReader(payload)
        while rdr.bytes_left() > 0 and rdr.data[rdr.pos] == MSG_PIGGYBACK:
            self._skip_piggyback(rdr)
        if rdr.bytes_left() == 0:
            return self._status_message()
        message_type = rdr.u8()
        if message_type == 1:                 # PROTOCOL (nessun fn/seq)
            return self._protocol_response()
        if message_type == 2:                 # DATA_TYPES (nessun fn/seq)
            return self._data_types_response()
        function_code = rdr.u8()
        rdr.u8()                              # sequence number
        if message_type != 3:                 # TNS_MSG_TYPE_FUNCTION
            self._dbg(f"messaggio inatteso type={message_type} "
                      f"fn={function_code}")
            return self._status_message()
        try:
            return self._dispatch(function_code, rdr)
        except OrabridgeError as e:
            return self._error_message(e.num, e.message, e.pos, 0)
        except Exception as e:  # noqa: BLE001
            self._dbg("ECCEZIONE:", type(e).__name__, e)
            if self.log:
                self.log("payload:", rdr.data[:200].hex())
                self.log("pos:", rdr.pos)
            return self._error_message(
                3113, "ORA-03113: end-of-file on communication channel", 0, 0)

    def _protocol_response(self) -> bytes:
        """Risposta al PROTOCOL del client: caps del server che degradano il
        client al field version 6 (11.2): formati piu' semplici per tutti."""
        w = TTCWriter()
        w.u8(1)                               # TNS_MSG_TYPE_PROTOCOL
        w.u8(6)                               # server protocol version
        w.u8(0)
        w.raw(PROTOCOL_BANNER.encode("utf-8") + b"\x00")
        w.u16le(873)                          # charset AL32UTF8
        w.u8(0)                               # server flags
        w.u16le(0)                            # num elements
        fdo = bytearray(16)
        fdo[9], fdo[10] = 0x03, 0x69          # ncharset 873
        w.u16be(len(fdo))
        w.raw(bytes(fdo))
        compile_caps = bytearray(55)
        compile_caps[7] = 6                   # TNS_CCAP_FIELD_VERSION_11_2
        w.length_prefixed(bytes(compile_caps))
        runtime_caps = bytearray(11)
        runtime_caps[6] = 0x04                # TNS_RCAP_TTC_32K
        w.length_prefixed(bytes(runtime_caps))
        return w.getvalue()

    @staticmethod
    def _data_types_response() -> bytes:
        """Risposta DATA_TYPES: nessuna conversione (lista vuota)."""
        w = TTCWriter()
        w.u8(2)
        w.u16be(0)                            # terminatore
        return w.getvalue()

    def _dispatch(self, fn: int, rdr: TTCReader) -> bytes:
        if fn == FUNC_AUTH_1:
            return self._auth_phase_one(rdr)
        if fn == FUNC_AUTH_2:
            return self._auth_phase_two(rdr)
        if fn in (FUNC_EXECUTE, FUNC_REEXECUTE, FUNC_REEXECUTE_FETCH):
            return self._execute_full(fn, rdr)
        if fn == FUNC_FETCH:
            return self._fetch(rdr)
        if fn == FUNC_COMMIT:
            if self.pg:
                self.pg.commit()
            return self._error_message(0, "", 0, 0, with_params=False)
        if fn == FUNC_ROLLBACK:
            if self.pg:
                self.pg.rollback()
            return self._error_message(0, "", 0, 0, with_params=False)
        if fn == FUNC_PING:
            return self._status_message()
        if fn == FUNC_LOGOFF:
            if self.pg:
                self.pg.rollback()
                self.pg.close()
            return self._status_message()
        self._dbg(f"funzione TTC non supportata: {fn}")
        raise OrabridgeError(900, f"ORA-00900: funzione TTC {fn} non "
                                  "supportata dal proxy")

    # ==================================================================
    # Autenticazione
    # ==================================================================
    @staticmethod
    def _read_kv_pairs(rdr: TTCReader, count: int) -> dict:
        pairs = {}
        for _ in range(count):
            key = rdr.read_str_with_length()
            value = rdr.read_str_with_length()
            flags = rdr.ub4()
            pairs[key] = (value, flags)
        return pairs

    @staticmethod
    def _read_auth_header(rdr: TTCReader) -> tuple[str | None, int]:
        has_user = rdr.u8()
        user_len = rdr.ub4()
        rdr.ub4()                          # auth mode
        rdr.u8()
        num_pairs = rdr.ub4()
        rdr.u8()
        rdr.u8()
        user = None
        if has_user and user_len:
            user = rdr.read_str()
        return user, num_pairs

    def _auth_phase_one(self, rdr: TTCReader) -> bytes:
        user, num_pairs = self._read_auth_header(rdr)
        if user:
            self.user = user
        self._read_kv_pairs(rdr, num_pairs)
        self._dbg("auth fase 1, utente:", self.user)
        # l'O5LOGON 11g richiede che il server conosca la password gia' in
        # fase 1 (cifra la sua meta' di chiave con il suo hash): gli utenti
        # non configurati vengono rifiutati subito
        if self.known_password is not None and self.user:
            self.auth.user = self.user
            self.auth.set_expected_password(self.known_password)
        if self.auth.encrypted_a_hex is None:
            return self._error_message(1017, ora_message(1017), 0, 0)
        w = TTCWriter()
        Session._write_param_message(w, self.auth.phase1_params())
        w.u8(MSG_ERROR)
        self._write_error_body(w, 0, "", 0, 0)
        return w.getvalue()

    def _auth_phase_two(self, rdr: TTCReader) -> bytes:
        user, num_pairs = self._read_auth_header(rdr)
        if user:
            self.user = user
        pairs = self._read_kv_pairs(rdr, num_pairs)
        sesskey = (pairs.get("AUTH_SESSKEY") or ("", 0))[0]
        password_hex = (pairs.get("AUTH_PASSWORD") or ("", 0))[0]
        self._dbg("auth fase 2, utente:", self.user)
        try:
            part_b = self.auth.open_client_key(sesskey)
            if part_b is None:
                raise OrabridgeError(1017, ora_message(1017))
            combo = derive_combo_key(part_b, self.auth.part_a,
                                     self.auth.csk_salt,
                                     self.auth.iterations)
            password = None
            if password_hex:
                raw = decrypt_password(combo, password_hex)
                if raw:
                    pad = raw[-1]
                    if 1 <= pad <= 16 and raw.endswith(bytes([pad]) * pad):
                        raw = raw[:-pad]
                    password = raw.decode("utf-8", "replace")
            expected = self.known_password
            if password is not None and expected is not None \
                    and password != expected:
                raise OrabridgeError(1017, ora_message(1017))
            if password is None:
                password = expected or ""

            from .pg import PgSession
            self.pg = PgSession(self.pg_host, self.pg_port, self.pg_db)
            self.pg.connect(self.user or "testapp", password)
        except OrabridgeError:
            raise
        except Exception as e:  # noqa: BLE001
            self._dbg("autenticazione fallita:", e)
            raise OrabridgeError(1017, ora_message(1017))
        params = [
            ("AUTH_VERSION_NO", str(SERVER_VERSION_NUM), 0),
            ("AUTH_SESSION_ID", "1", 0),
            ("AUTH_SERIAL_NUM", "1", 0),
            ("AUTH_SVR_RESPONSE", self.auth.server_response(combo), 0),
            ("AUTH_SC_DB_NAME", "ORABRIDGE", 0),
            ("AUTH_SC_DBUNIQUE_NAME", "ORABRIDGE", 0),
            ("AUTH_SC_SERVICE_NAME", "FREEPDB1", 0),
            ("AUTH_INSTANCENAME", "orabridge", 0),
            ("AUTH_MAX_OPEN_CURSORS", "50", 0),
            ("AUTH_MAX_IDEN_LENGTH", "128", 0),
            ("SESSION_MAX_STRING_SIZE", "32767", 0),
        ]
        w = TTCWriter()
        Session._write_param_message(w, params)
        w.u8(MSG_STATUS)
        w.ub4(0)
        w.ub2(0)
        return w.getvalue()

    @staticmethod
    def _write_param_message(w: TTCWriter, params):
        w.u8(8)                            # TNS_MSG_TYPE_PARAMETER
        w.ub2(len(params))
        for key, value, flags in params:
            w.write_bytes_with_two_lengths(key)
            w.write_bytes_with_two_lengths(value)
            w.ub4(flags)

    # ==================================================================
    # Execute
    # ==================================================================
    @staticmethod
    def _parse_bind_metadata(rdr: TTCReader, count: int,
                             names: list[str]) -> list[BindParam]:
        params = []
        for i in range(count):
            p = BindParam()
            p.ora_type = rdr.u8()
            rdr.u8()                       # flag
            rdr.u8()                       # precision
            rdr.u8()                       # scale
            rdr.ub4()                      # buffer size
            rdr.ub4()                      # max elements
            rdr.ub8()                      # cont flag
            rdr.read_bytes_with_length()   # OID
            rdr.ub2()                      # version
            rdr.ub2()                      # csid
            rdr.u8()                       # csfrm
            rdr.ub4()                      # max chars (lob prefetch)
            if i < len(names):
                p.name = names[i]
            params.append(p)
        return params

    @staticmethod
    def _parse_bind_values(rdr: TTCReader, params: list[BindParam]):
        for p in params:
            if p.ora_type == ORA_TYPE_CURSOR:
                rdr.u8()                   # marker cursore (valore 1,0)
                continue
            raw = rdr.length_prefixed_bytes()
            p.value = Session._decode_bind_value(p.ora_type, raw)

    @staticmethod
    def _decode_bind_value(ora_type: int, raw: bytes | None):
        if raw is None:
            return None
        if ora_type == ORA_TYPE_NUMBER:
            return decode_number(raw)
        if ora_type == ORA_TYPE_DATE:
            return decode_date(raw)
        if ora_type in (ORA_TYPE_TIMESTAMP, ORA_TYPE_TIMESTAMP_TZ):
            return decode_timestamp(raw)
        if ora_type == ORA_TYPE_INTERVAL_DS:
            return decode_interval_ds(raw)
        return raw

    def _execute_full(self, fn: int, rdr: TTCReader) -> bytes:
        if fn != FUNC_EXECUTE:
            # reexecute: il proxy assegna cursor id solo ai REF CURSOR,
            # quindi non dovrebbe mai arrivare; gestito come errore chiaro
            rdr.ub4()                      # cursor id
            rdr.ub4()                      # num iters
            rdr.ub4()
            rdr.ub4()
            raise OrabridgeError(900, "ORA-00900: reexecute non supportato")
        options = rdr.ub4()
        cursor_id = rdr.ub4()
        has_sql = rdr.u8()
        rdr.ub4()                          # sql length
        rdr.u8()                           # ptr vector
        rdr.ub4()                          # 13
        rdr.u8()
        rdr.u8()
        rdr.ub4()                          # prefetch buffer size
        num_iters = rdr.ub4()
        rdr.ub4()                          # max long
        binds_ptr = rdr.u8()
        num_binds = rdr.ub4()
        rdr.u8(); rdr.u8(); rdr.u8(); rdr.u8(); rdr.u8()
        define_ptr = rdr.u8()
        num_defines = rdr.ub4()
        rdr.ub4()                          # registration lsb
        rdr.u8()                           # objlist
        rdr.u8()                           # objlen ptr
        rdr.u8()                           # blv
        rdr.ub4()                          # blvl
        rdr.u8()                           # dnam
        rdr.ub4()                          # dnaml
        rdr.ub4()                          # registration msb
        # blocco arraydmlrowcounts: presente sia col flag sia senza
        # (u8 pointer, ub4 size, u8 pointer)
        rdr.u8()
        rdr.ub4()
        rdr.u8()
        sql_text = None
        if has_sql:
            # sql subito dopo (write_bytes_with_length = ub1-len prefix),
            # poi al8i4[0] (flag parse)
            sql_text = rdr.length_prefixed_bytes()
            if sql_text is not None:
                sql_text = sql_text.decode("utf-8")
            rdr.ub4()                      # al8i4[0] (parse flag)
        exec_count = rdr.ub4()             # al8i4[1]
        for _ in range(5):                 # al8i4[2..6]
            rdr.ub4()
        is_query = rdr.ub4()               # al8i4[7]
        rdr.ub4()                          # al8i4[8]
        rdr.ub4()                          # al8i4[9] exec flags
        rdr.ub4()                          # al8i4[10] fetch orientation
        rdr.ub4()                          # al8i4[11] fetch pos
        rdr.ub4()                          # al8i4[12]
        bind_params: list[BindParam] = []
        is_returning = bool(re.search(r"(?i)\bRETURNING\b[\s\S]*\bINTO\b",
                                      sql_text or ""))
        if define_ptr and num_defines:
            Session._parse_bind_metadata(rdr, num_defines, ["?"])
        if binds_ptr and num_binds:
            names = find_bind_names(sql_text or "")
            bind_params = Session._parse_bind_metadata(rdr, num_binds, names)
            # i bind RETURNING non portano valori nella richiesta
            if not is_query and not is_returning:
                for _ in range(min(1, max(1, exec_count))):
                    if rdr.u8() == MSG_ROW_DATA:
                        Session._parse_bind_values(rdr, bind_params)
                    break
        self._dbg(f"exec opt={options:#x} binds={num_binds} "
                  f"q={is_query} ret={is_returning} "
                  f"sql={(sql_text or '')[:90]!r}")
        if sql_text is None:
            if cursor_id:
                # execute senza sql su un cursore noto: serve le righe bufferate
                return self._serve_cursor_rows(cursor_id, num_iters)
            raise OrabridgeError(900, "ORA-00900: statement senza testo")

        upper = sql_text.strip().upper()
        if upper.startswith(("BEGIN", "DECLARE", "CALL")):
            return self._execute_plsql(sql_text, bind_params, num_binds)
        if upper.startswith(("ROLLBACK", "COMMIT", "SAVEPOINT")):
            return self._execute_transaction(upper)
        if is_returning:
            return self._execute_returning(sql_text, bind_params, num_binds)
        return self._execute_sql(sql_text, bind_params, num_binds,
                                 num_iters, options)

    def _execute_transaction(self, upper: str) -> bytes:
        if upper.startswith("ROLLBACK"):
            self.pg.rollback()
        elif upper.startswith("COMMIT"):
            self.pg.commit()
        return self._error_message(0, "", 0, 0)

    @staticmethod
    def _bind_args(bind_params: list[BindParam]) -> dict:
        args = {}
        for p in bind_params:
            v = p.value
            if isinstance(v, (bytes, bytearray)):
                try:
                    v = bytes(v).decode("utf-8")
                except UnicodeDecodeError:
                    pass
            args[p.name] = v
            # sqlglot puo' preservare il caso originale dei placeholder:
            # si copre anche la variante minuscola
            args[p.name.lower()] = v
            if p.ora_type == ORA_TYPE_CURSOR:
                args.pop(p.name, None)    # il cursore non e' un argomento PG
                args.pop(p.name.lower(), None)
        return args

    def _execute_sql(self, sql_text: str, bind_params, num_binds,
                     num_iters: int, options: int) -> bytes:
        args = self._bind_args(bind_params) if num_binds else None
        if not (options & (EXEC_EXECUTE | EXEC_FETCH)):
            # passata DEFINE (describe-only): il client rifara' la richiesta
            self._dbg("define-only pass")
            return self._error_message(0, "", 0, 0)
        pg_sql = translate_sql(sql_text)
        if num_binds:
            pg_sql, _ = replace_bind_placeholders(pg_sql)
        self._dbg("PG:", pg_sql[:160])
        meta, rows = self.pg.run(pg_sql, args)
        if not meta:
            return self._error_message(0, "", 0, 0,
                                       rowcount=self.pg.last_rowcount)
        # il client alloca il buffer righe in base a num_iters: mai superarlo.
        # Se restano righe, si assegna un cursore server-side per il FETCH.
        deliver = rows if num_iters <= 0 else rows[:num_iters]
        rest = rows[len(deliver):]
        if not rest:
            return self._query_response(meta, deliver, 0)
        cursor_id = self.next_ref_id
        self.next_ref_id += 1
        self.ref_cursors[cursor_id] = {"meta": meta, "rows": rest, "pos": 0}
        self._dbg(f"query parziale: consegnate {len(deliver)}, "
                  f"cursore {cursor_id} con {len(rest)} righe")
        return self._query_response(meta, deliver, cursor_id)

    def _eocs(self) -> int:
        """Flag end-of-call-status: bit 0x2 = transazione in corso."""
        if self.pg is not None and self.pg.conn is not None:
            try:
                st = int(self.pg.conn.info.transaction_status)
                if st in (2, 3):          # INTRANS / INERROR
                    return 0x0002
            except Exception:  # noqa: BLE001
                pass
        return 0

    def _execute_returning(self, sql_text: str, bind_params,
                           num_binds: int) -> bytes:
        """INSERT/UPDATE ... RETURNING x INTO :bind.

        Traduzione: si rimuove 'INTO :bind' (il RETURNING resta, PostgreSQL
        lo supporta nativamente) e le righe ritornate vengono spedite come
        ROW_DATA con, per ogni bind, ub4 n righe + valori + sb4, poi
        PARAMETER con i valori scratch e ERROR(0) con il rowcount.
        Struttura specchiata dalla risposta reale di Oracle 26ai.
        """
        args = self._bind_args(bind_params) if num_binds else None
        pg_sql = translate_sql(sql_text)
        pg_sql = re.sub(r"(?is)\bINTO\s+:[\w$#]+(\s*,\s*:[\w$#]+)*\s*$", "",
                        pg_sql).strip()
        if num_binds:
            pg_sql, _ = replace_bind_placeholders(pg_sql)
        self._dbg("PG returning:", pg_sql[:160])
        meta, rows = self.pg.run(pg_sql, args)
        w = TTCWriter()
        w.u8(MSG_ROW_DATA)
        for p in bind_params:
            w.ub4(len(rows))
            for row in rows:
                Session._write_column_value(w, p.ora_type,
                                            row[0] if row else None)
                w.sb4(0)                   # actual_num_bytes
        # PARAMETER con scratch buffer (al8o4l=6 + 6 ub4, il client li salta)
        w.u8(8)
        w.ub2(6)
        for _ in range(6):
            w.ub4(0)
        w.ub2(0)                           # al8txl
        w.ub2(0)                           # kv pairs
        w.ub2(0)                           # registration
        w.u8(MSG_ERROR)
        self._write_error_body(w, 0, "", 0, 0, rowcount=self.pg.last_rowcount,
                               eocs=self._eocs())
        return w.getvalue()

    def _execute_plsql(self, sql_text: str, bind_params, num_binds) -> bytes:
        block = PlsqlBlock(sql_text)
        if not block.supported:
            raise OrabridgeError(
                6550, ora_message(6550, ("1", "1",
                                         block.error or "non supportato")))
        for stmt in block.statements:
            m = re.match(
                r"(?i)raise_application_error\s*\(\s*-(\d+)\s*,\s*'(.+?)'\s*\)",
                stmt, re.S)
            if m:
                num = int(m.group(1))          # 20001..20999
                msg = m.group(2).replace("''", "'")
                raise OrabridgeError(num, f"ORA-{num}: {msg}")
        args = self._bind_args(bind_params) if num_binds else {}

        # bind di tipo CURSOR: l'istruzione che lo tocca apre un REF CURSOR
        cursor_binds = [p for p in bind_params if p.ora_type == ORA_TYPE_CURSOR]
        ref_meta, ref_rows, ref_id = None, None, 0
        cursor_call_idx: set[int] = set()
        for idx, stmt in enumerate(block.statements):
            if cursor_binds and any(f":{p.name}".lower() in stmt.lower()
                                    for p in cursor_binds):
                # apre il cursore: rimuove l'argomento cursore dalla chiamata
                # (il lato PG della funzione non lo prevede) e materializza
                call = re.sub(r"(?i),\s*:[\w$#]+\s*\)", ")", stmt)
                if call.strip().endswith(")"):
                    pg_call = translate_sql("SELECT * FROM " + call)
                    pg_call, _ = replace_bind_placeholders(pg_call)
                    ref_meta, ref_rows = self.pg.run(pg_call, args)
                    ref_id = self.next_ref_id
                    self.next_ref_id += 1
                    self.ref_cursors[ref_id] = {"meta": ref_meta,
                                                "rows": ref_rows, "pos": 0}
                    cursor_call_idx.add(idx)
                    continue

        translated = block.translate()
        out_values: dict[str, object] = {}

        def _run_body():
            for idx, call in enumerate(translated["calls"]):
                if idx in cursor_call_idx:
                    continue
                self.pg.run(call, args)
            if translated["select"]:
                _meta, rows = self.pg.run(translated["select"], args)
                if rows:
                    for bind, value in zip(translated["assignment_order"],
                                           rows[0]):
                        out_values[bind] = value

        try:
            _run_body()
        except OrabridgeError as e:
            if not block.exception_other:
                raise
            # simulazione WHEN OTHERS: SQLCODE/SQLERRM dal blocco catturato
            handler = block.translate_handler(e.num, e.message)
            if handler["select"]:
                _meta, rows = self.pg.run(handler["select"], args)
                if rows:
                    for bind, value in zip(handler["assignment_order"],
                                           rows[0]):
                        out_values[bind] = value

        w = TTCWriter()
        w.u8(8); w.ub2(0); w.ub2(0); w.ub2(0); w.ub2(0)
        w.u8(MSG_IO_VECTOR)
        w.u8(0)                            # flag
        w.ub2(num_binds % 256)             # num requests
        w.ub4(num_binds // 256)            # num iters
        w.ub4(1)                           # iters this time
        w.ub2(0)                           # uac buffer length
        w.ub2(0)                           # bit vector size
        w.ub2(0)                           # rowid size
        for _p in bind_params:
            w.u8(BIND_DIR_INOUT)
        for p in bind_params:
            w.u8(MSG_ROW_DATA)
            if p.ora_type == ORA_TYPE_CURSOR and ref_id:
                # cursore: ub1 marker + describe figlia + ub2 cursor id
                w.u8(1)
                Session._write_describe_info(w, ref_meta)
                w.ub2(ref_id)
            else:
                value = out_values.get(p.name, p.value)
                Session._write_column_value(w, p.ora_type, value)
            w.sb4(0)                       # actual_num_bytes
        w.u8(MSG_ERROR)
        self._write_error_body(w, 0, "", 0, 0)
        return w.getvalue()

    # ------------------------------------------------------------------
    def _serve_cursor_rows(self, cursor_id: int, num_iters: int) -> bytes:
        """Serve le righe bufferate di un cursore (REF CURSOR o query
        parziale) per un execute/fetch senza testo SQL."""
        entry = self.ref_cursors.get(cursor_id)
        if entry is None:
            raise OrabridgeError(1007,
                                 "ORA-01007: variable not in select list")
        meta, rows, pos = entry["meta"], entry["rows"], entry["pos"]
        batch = rows[pos:pos + (num_iters or len(rows))]
        pos += len(batch)
        done = pos >= len(rows)
        entry["pos"] = pos
        w = TTCWriter()
        w.u8(8); w.ub2(0); w.ub2(0); w.ub2(0); w.ub2(0)
        w.u8(MSG_DESCRIBE_INFO)
        w.u8(0)
        Session._write_describe_info(w, meta)
        if batch:
            Session._write_row_header(w)
            Session._write_rows(w, meta, batch)
        w.u8(MSG_ERROR)
        if done:
            self._write_error_body(w, 1403, ora_message(1403), 0, cursor_id)
        else:
            self._write_error_body(w, 0, "", 0, cursor_id)
        return w.getvalue()

    def _fetch(self, rdr: TTCReader) -> bytes:
        cursor_id = rdr.ub4()
        array_size = rdr.ub4()
        entry = self.ref_cursors.get(cursor_id)
        if entry is None:
            raise OrabridgeError(1007,
                                 "ORA-01007: variable not in select list")
        meta, rows, pos = entry["meta"], entry["rows"], entry["pos"]
        batch = rows[pos:pos + array_size]
        pos += len(batch)
        done = pos >= len(rows)
        entry["pos"] = pos
        w = TTCWriter()
        if batch:
            Session._write_row_header(w)
            Session._write_rows(w, meta, batch)
        w.u8(MSG_ERROR)
        if done:
            self._write_error_body(w, 1403, ora_message(1403), 0, cursor_id)
        else:
            self._write_error_body(w, 0, "", 0, cursor_id)
        return w.getvalue()

    # ==================================================================
    # Costruzione risposte
    # ==================================================================
    @staticmethod
    def _write_error_body(w: TTCWriter, num: int, message: str, pos: int,
                          cursor_id: int, rowcount: int = 0, eocs: int = 0):
        w.ub4(eocs)                    # end of call status
        w.ub2(0)                       # end to end seq
        w.ub4(0)                       # current row number
        w.ub2(0)                       # error number (legacy)
        w.ub2(0)                       # array elem error
        w.ub2(0)                       # array elem error
        w.ub2(cursor_id)               # cursor id
        w.sb2(pos)                     # error position
        w.u8(0)                        # sql type
        w.u8(0)                        # fatal
        w.u8(0)                        # flags
        w.u8(0)                        # user cursor options
        w.u8(0)                        # UPI parameter
        w.u8(0)                        # flags
        # rowid: ub4 rba, ub2 partition, ub1, ub4 block, ub2 slot
        w.ub4(0); w.ub2(0); w.u8(0); w.ub4(0); w.ub2(0)
        w.ub4(0)                       # OS error
        w.u8(0)                        # statement number
        w.u8(0)                        # call number
        w.ub2(0)                       # padding
        w.ub4(0)                       # success iters
        w.ub4(0)                       # oerrdd (bytes with length vuoto)
        w.ub2(0)                       # batch error codes
        w.ub4(0)                       # batch error offsets
        w.ub2(0)                       # batch error messages
        w.ub4(num)                     # error number (extended)
        w.ub8(rowcount)                # row number (extended) = rowcount DML
        w.length_prefixed((message or "").encode("utf-8"))

    @staticmethod
    def _error_message(num: int, message: str, pos: int, cursor_id: int,
                       rowcount: int = 0, with_params: bool = True) -> bytes:
        w = TTCWriter()
        if with_params:
            w.u8(8); w.ub2(0); w.ub2(0); w.ub2(0); w.ub2(0)
        w.u8(MSG_ERROR)
        Session._write_error_body(w, num, message, pos, cursor_id, rowcount)
        return w.getvalue()

    @staticmethod
    def _status_message() -> bytes:
        w = TTCWriter()
        w.u8(MSG_STATUS)
        w.ub4(0)
        w.ub2(0)
        return w.getvalue()

    @staticmethod
    def _write_describe_info(w: TTCWriter, meta):
        """Blocco DESCRIBE_INFO (senza il byte di skip iniziale)."""
        w.ub4(sum(m["buffer_size"] for m in meta))
        w.ub4(len(meta))
        if meta:
            w.u8(0)
        for m in meta:
            Session._write_metadata(w, m)
        w.ub4(0)                           # current date
        w.ub4(0); w.ub4(0); w.ub4(0); w.ub4(0); w.ub4(0)

    @staticmethod
    def _query_response(meta, rows, cursor_id: int = 0) -> bytes:
        w = TTCWriter()
        w.u8(8); w.ub2(0); w.ub2(0); w.ub2(0); w.ub2(0)
        w.u8(MSG_DESCRIBE_INFO)
        w.u8(0)                            # skip_bytes
        Session._write_describe_info(w, meta)
        if rows:
            Session._write_row_header(w)
            Session._write_rows(w, meta, rows)
        w.u8(MSG_ERROR)
        if cursor_id:
            # restano righe: ERROR(0) con il cursor id per il FETCH successivo
            Session._write_error_body(w, 0, "", 0, cursor_id)
        else:
            # fine righe: ERROR 1403 viene assorbito dal client come eof fetch
            Session._write_error_body(w, 1403, ora_message(1403), 0, 0)
        return w.getvalue()

    @staticmethod
    def _write_metadata(w: TTCWriter, m: dict):
        w.u8(m["ora_type"])
        w.u8(0)                            # flags
        w.sb1(m["precision"])
        w.sb1(m["scale"])
        w.ub4(m["buffer_size"])
        w.ub4(0)                           # max array elements
        w.ub8(0)                           # cont flags
        w.ub4(0)                           # oid (bytes with length vuoto)
        w.ub2(0)                           # version
        w.ub2(m["csid"])
        w.u8(m["csfrm"])
        w.ub4(m["max_size"])
        w.u8(m["nulls_allowed"])
        w.u8(0)                            # v7 length
        w.write_bytes_with_two_lengths(m["name"])
        w.write_bytes_with_two_lengths(None)
        w.write_bytes_with_two_lengths(m["name"])
        w.ub2(0)                           # column position
        w.ub4(0)                           # uds flags

    @staticmethod
    def _write_row_header(w: TTCWriter):
        w.u8(MSG_ROW_HEADER)
        w.u8(0)                            # flags
        w.ub2(1)                           # num requests
        w.ub4(0)                           # iteration
        w.ub4(1)                           # num iters
        w.ub2(0)                           # buffer length
        w.ub4(0)                           # bit vector size
        w.ub4(0)                           # rxhrid

    @staticmethod
    def _write_rows(w: TTCWriter, meta, rows):
        # una riga = un messaggio ROW_DATA (il client processa una riga
        # per messaggio e incrementa row_index a ogni messaggio)
        for row in rows:
            w.u8(MSG_ROW_DATA)
            for m, value in zip(meta, row):
                Session._write_column_value(w, m["ora_type"], value)

    @staticmethod
    def _write_column_value(w: TTCWriter, ora_type: int, value):
        try:
            data = encode_column_value(ora_type, value)
        except (ValueError, OverflowError):
            data = str(value).encode("utf-8")
        w.length_prefixed(data)

    # ==================================================================
    def _skip_piggyback(self, rdr: TTCReader):
        rdr.u8()                           # type piggyback
        code = rdr.u8()
        rdr.u8()                           # seq
        self._dbg("piggyback client:", code)
        if code == 105:                    # CLOSE_CURSORS
            count = rdr.ub4()
            for _ in range(count):
                cid = rdr.ub4()
                self.ref_cursors.pop(cid, None)
        elif code == 152:                  # SET_SCHEMA
            rdr.u8()
            rdr.read_str_with_length()
        elif code == 204:                  # ALTER_SESSION
            rdr.ub4()
            rdr.u8()
            num = rdr.ub4()
            self._read_kv_pairs(rdr, num)
        elif code == 176:                  # SESSION_STATE
            rdr.ub8()
        else:
            raise OrabridgeError(
                900, f"ORA-00900: piggyback {code} non gestito dal proxy")
