"""Backend PostgreSQL di una sessione proxy.

Mantiene la connessione PG per sessione (semantica transazionale Oracle:
la transazione resta aperta finche' non arriva COMMIT/ROLLBACK), i cursori
con buffer di righe per i REF CURSOR e per i risultati oltre l'SDU.
"""
import psycopg
from psycopg import sql as pgsql

from .errors import OrabridgeError, from_pg_error
from .types import (ORA_TYPE_CHAR, ORA_TYPE_CLOB, ORA_TYPE_DATE,
                    ORA_TYPE_INTERVAL_DS, ORA_TYPE_NUMBER, ORA_TYPE_RAW,
                    ORA_TYPE_TIMESTAMP, ORA_TYPE_VARCHAR, ORA_TYPE_LONG)

PG_OID_MAP = {
    16: ("BOOLEAN", ORA_TYPE_NUMBER),
    18: ("CHAR", ORA_TYPE_CHAR),
    20: ("NUMBER", ORA_TYPE_NUMBER),
    21: ("NUMBER", ORA_TYPE_NUMBER),
    23: ("NUMBER", ORA_TYPE_NUMBER),
    25: ("VARCHAR2", ORA_TYPE_VARCHAR),
    700: ("NUMBER", ORA_TYPE_NUMBER),
    701: ("NUMBER", ORA_TYPE_NUMBER),
    1042: ("CHAR", ORA_TYPE_CHAR),
    1043: ("VARCHAR2", ORA_TYPE_VARCHAR),
    1082: ("DATE", ORA_TYPE_DATE),
    1114: ("TIMESTAMP", ORA_TYPE_TIMESTAMP),
    1184: ("TIMESTAMP", ORA_TYPE_TIMESTAMP),
    1186: ("INTERVAL_DS", ORA_TYPE_INTERVAL_DS),
    1700: ("NUMBER", ORA_TYPE_NUMBER),
    3802: ("VARCHAR2", ORA_TYPE_VARCHAR),   # jsonb -> testo
    114: ("RAW", ORA_TYPE_RAW),
    17: ("RAW", ORA_TYPE_RAW),
}
MAX_STRING_BUFFER = 32767
ORA_BUFFER_SIZES = {
    ORA_TYPE_NUMBER: 22,
    ORA_TYPE_DATE: 7,
    ORA_TYPE_TIMESTAMP: 11,
    ORA_TYPE_INTERVAL_DS: 11,
    ORA_TYPE_RAW: MAX_STRING_BUFFER,
    ORA_TYPE_VARCHAR: MAX_STRING_BUFFER,
    ORA_TYPE_CHAR: MAX_STRING_BUFFER,
    ORA_TYPE_LONG: MAX_STRING_BUFFER,
}


def column_metadata(name: str, pg_type_oid: int, precision=None,
                    scale=None, nullable=True) -> dict:
    ora_name, ora_type = PG_OID_MAP.get(pg_type_oid, ("VARCHAR2",
                                                      ORA_TYPE_VARCHAR))
    # i tipi carattere richiedono CS_FORM_IMPLICIT (1) nella metadata:
    # con csfrm=0 il client non riconosce il tipo (DPY-3006)
    csfrm = 1 if ora_type in (ORA_TYPE_VARCHAR, ORA_TYPE_CHAR,
                              ORA_TYPE_LONG, ORA_TYPE_CLOB) else 0
    return {
        "name": name.upper(),
        "ora_type": ora_type,
        "ora_type_name": ora_name,
        "precision": int(precision) if precision else 0,
        "scale": int(scale) if scale else 0,
        "buffer_size": ORA_BUFFER_SIZES.get(ora_type, MAX_STRING_BUFFER),
        "max_size": MAX_STRING_BUFFER,
        "csid": 873 if csfrm else 0,
        "csfrm": csfrm,
        "nulls_allowed": 1 if nullable else 0,
    }


class PgSession:
    def __init__(self, host: str, port: int, dbname: str):
        self.host = host
        self.port = port
        self.dbname = dbname
        self.conn: psycopg.Connection | None = None
        self.user = None
        self.cursors: dict[int, dict] = {}   # id -> {rows, meta, pos, done}
        self.next_cursor_id = 1

    # ------------------------------------------------------------------
    def connect(self, user: str, password: str) -> None:
        self.user = user
        try:
            self.conn = psycopg.connect(
                host=self.host, port=self.port, dbname=self.dbname,
                user=user.lower(), password=password,
                connect_timeout=10)
        except psycopg.Error as e:
            self.conn = None
            raise from_pg_error(e)

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None

    # ------------------------------------------------------------------
    def run(self, sql_pg: str, params: dict | None = None):
        """Esegue uno statement. Ritorna (metadata, righe).

        Le righe sono sempre materializzate integralmente (dataset di test).
        """
        if self.conn is None:
            raise OrabridgeError(1017, "ORA-01017: not connected")
        try:
            with self.conn.cursor() as cur:
                cur.execute(sql_pg, params or None)
                self.last_rowcount = cur.rowcount
                if cur.description is None:
                    return [], []
                meta = [
                    column_metadata(d.name, d.type_code,
                                    precision=d.precision, scale=d.scale)
                    for d in cur.description
                ]
                rows = cur.fetchall()
                return meta, [tuple(r) for r in rows]
        except psycopg.Error as e:
            self.conn.rollback()
            raise from_pg_error(e)

    def commit(self):
        if self.conn is not None:
            self.conn.commit()

    def rollback(self):
        if self.conn is not None:
            self.conn.rollback()

    def commit(self):
        if self.conn is not None:
            self.conn.commit()

    def rollback(self):
        if self.conn is not None:
            self.conn.rollback()
