"""Motore di traduzione Oracle -> PostgreSQL in tempo reale.

Pipeline: pre-regole testuali (+) outer join, LISTAGG, ROWNUM, dual, ecc. ->
sqlglot (read=oracle, write=postgres) -> post-regole (DATE_TRUNC, CURRENT_*)
-> sostituzione placeholder :bind -> %(bind)s per psycopg.
Include un gestore semplificato di blocchi PL/SQL (assegnamenti e chiamate).
"""
import re

import sqlglot

# ---------------------------------------------------------------------------
# Bind: parser dei nomi placeholder, stesso ordine del client python-oracledb
# ---------------------------------------------------------------------------
BIND_NAME_RE = re.compile(
    r"""(?<![:\w]):([A-Za-z_][A-Za-z0-9_$#]*)|:(\d+)""")


def find_bind_names(sql: str) -> list[str]:
    """Nomi placeholder in ordine di apparizione (uno per occorrenza,
    come fa il client per SQL non-PL/SQL). Ignora : dentro stringhe,
    commenti e i cast '::'."""
    names: list[str] = []
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch == "'":                       # stringa letterale
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
        elif ch == "-" and sql[i:i + 2] == "--":
            j = sql.find("\n", i)
            i = n if j < 0 else j
        elif ch == "/" and sql[i:i + 2] == "/*":
            j = sql.find("*/", i)
            i = n if j < 0 else j + 2
        elif ch == '"' or ch == '`':        # identificatore quotato
            q = ch
            i += 1
            while i < n and sql[i] != q:
                i += 1
            i += 1
        elif ch == ':':
            if i + 1 < n and sql[i + 1] == ':':
                i += 2
                continue
            m = BIND_NAME_RE.match(sql, i)
            if m:
                name = (m.group(1) or m.group(2)).upper()
                names.append(name)
                out.append(f"%({name})s")
                i = m.end()
                continue
            i += 1
        else:
            i += 1
    return names


def replace_bind_placeholders(sql: str) -> tuple[str, list[str]]:
    """Sostituisce :name con %(name)s mantenendo l'ordine."""
    names = find_bind_names(sql)

    def _sub(match):
        name = (match.group(1) or match.group(2)).upper()
        return f"%({name})s"

    out = BIND_NAME_RE.sub(_sub, sql)
    # rimuove i placeholder dentro stringhe gia' gestiti? le stringhe non
    # contengono :bind perche' il parser qui sopra e' applicato a valle;
    # semplice protezione: niente.
    return out, names


# ---------------------------------------------------------------------------
# Pre-regole testuali su SQL Oracle (prima di sqlglot)
# ---------------------------------------------------------------------------
def strip_from_dual(sql: str) -> str:
    return re.sub(r"(?i)\bfrom\s+dual\b", "", sql)


def rewrite_rownum(sql: str) -> str:
    """Casi gestiti:
    - 'SELECT ... FROM (subquery) WHERE ROWNUM <= N' -> '... LIMIT N'
    - 'SELECT x, ROWNUM rnum FROM t ...'             -> ROW_NUMBER() OVER ()
    - 'WHERE ... ROWNUM <= N' semplice               -> LIMIT N (euristico)
    """
    m = re.search(r"(?i)\bROWNUM\s*(<=|<)\s*(\d+)", sql)
    if not m:
        # ROWNUM come espressione della lista SELECT (alias subito dopo)
        aliased = re.sub(
            r"(?i)\bROWNUM\b(?!\s*(?:<=|>=|<|>|=|<>|BETWEEN|IN))\s+(\w+)\b",
            r" ROW_NUMBER() OVER () AS \1", sql)
        if aliased != sql:
            return aliased
        return sql
    limit = m.group(2)
    # ROWNUM come espressione di select
    sql = re.sub(r"(?i)\bROWNUM\b(\s+\w+\s*[,\)])",
                 r" ROW_NUMBER() OVER () AS\1", sql)
    if "ROW_NUMBER" in sql:
        return sql
    # condizione top-level: rimuove il predicato e aggiunge LIMIT
    sql2 = re.sub(r"(?i)(and\s+)?\bROWNUM\s*(<=|<)\s*(\d+)\s*(and)?", "", sql)
    sql2 = re.sub(r"(?i)\bwhere\s*(order\s+by|\)|$)", r"\1", sql2)
    sql2 = sql2.rstrip()
    if sql2.endswith(";"):
        sql2 = sql2[:-1]
    return sql2 + f" LIMIT {int(limit)}"


def rewrite_plus_outer_join(sql: str) -> str:
    """Converte i predicati 'a.col(+) = b.col' in join esterni standard.

    Gestisce il caso classico a due/tre tabelle con un solo lato NULL:
    la tabella con (+) su tutte le sue colonne diventa la tabella
    null-generating (LEFT JOIN). Le condizioni spostate in ON vengono
    rimosse dal WHERE.
    """
    if "(+)" not in sql:
        return sql
    cond_texts: list[str] = []
    optional_tables: set[str] = set()
    plain_conds: list[tuple[str, str]] = []
    pattern = re.compile(
        r"(?i)([\w.]+)\s*\(\+\)\s*(=)\s*([\w.]+)|"
        r"([\w.]+)\s*(=)\s*([\w.]+)\s*\(\+\)")
    for m in pattern.finditer(sql):
        if m.group(1):
            left, right = m.group(1), m.group(3)
        else:
            left, right = m.group(4), m.group(6)
        cond_texts.append(m.group(0))
        plain_conds.append((left, right))
        optional_tables.add(left.split(".")[0])
    if not plain_conds:
        return sql.replace("(+)", "")
    m = re.search(r"(?is)\bFROM\b(.*?)(\bWHERE\b|ORDER\s+BY|GROUP\s+BY|$)",
                  sql)
    if m and plain_conds:
        from_part = m.group(1).strip()
        tables = [t.strip() for t in from_part.split(",") if t.strip()]
        if len(tables) >= 2:
            base = tables[0]
            alias_base = base.split()[-1].lower()
            joined = [f"FROM {base}"]
            for t in tables[1:]:
                alias = t.split()[-1].lower()
                kind = "LEFT" if alias in optional_tables else "INNER"
                on = " AND ".join(
                    f"{a} = {b}" for a, b in plain_conds
                    if {a.split(".")[0].lower(), b.split(".")[0].lower()}
                    == {alias, alias_base})
                joined.append(f"{kind} JOIN {t} ON {on}")
            sql = sql[:m.start()] + " ".join(joined) + " " + sql[m.end():]
            # rimuove le condizioni spostate in ON dal WHERE
            for cond in cond_texts:
                sql = re.sub(r"(?i)(and\s+)?" + re.escape(cond),
                             " ", sql, count=1)
            sql = re.sub(r"(?i)\bWHERE\s*(order\s+by|group\s+by|$)",
                         r"\1", sql)
            sql = re.sub(r"\s{2,}", " ", sql)
            return sql
    return sql.replace("(+)", "")


def pre_rules(sql: str) -> str:
    sql = rewrite_plus_outer_join(sql)
    sql = strip_from_dual(sql)
    sql = rewrite_rownum(sql)
    # SYSDATE -> CURRENT_DATE (aritmetica date coerente con Oracle)
    sql = re.sub(r"(?i)\bSYSDATE\b", "CURRENT_DATE", sql)
    # sequenze
    sql = re.sub(r"(?i)\b([\w$#]+)\.NEXTVAL\b", r"nextval('\1')", sql)
    sql = re.sub(r"(?i)\b([\w$#]+)\.CURRVAL\b", r"currval('\1')", sql)
    # DBMS_LOB.SUBSTR(col, n, start) -> substring(col, start, n)
    sql = re.sub(r"(?i)DBMS_LOB\.SUBSTR\(\s*([^,]+?)\s*,\s*([^,]+?)\s*,"
                 r"\s*([^)]+?)\s*\)", r"SUBSTRING(\1, \3, \2)", sql)
    # RAWTOHEX(x) -> UPPER(encode(x, 'hex')), con un livello di annidamento
    sql = re.sub(r"(?i)RAWTOHEX\(([^()]*(?:\([^()]*\))?[^()]*)\)",
                 r"UPPER(encode(\1::bytea, 'hex'))", sql)
    # sinonimo E -> emp (configurabile a valle)
    sql = re.sub(r"(?i)\bFROM\s+E\b(\s*[),;\s]|$)", "FROM emp\\1", sql)
    return sql


def post_rules(sql: str) -> str:
    sql = re.sub(r"(?i)DATE_TRUNC\(\s*'(DD|DAY)'", "DATE_TRUNC('day'", sql)
    sql = re.sub(r"(?i)DATE_TRUNC\(\s*'(MM|MONTH)'", "DATE_TRUNC('month'", sql)
    sql = re.sub(r"(?i)DATE_TRUNC\(\s*'(YYYY|YEAR)'", "DATE_TRUNC('year'", sql)
    # bug sqlglot: stringhe generate con doppi apici in STRING_AGG
    sql = re.sub(r'STRING_AGG\(([^,]+),\s*"([^"]*)"', r"STRING_AGG(\1, '\2'",
                 sql)
    # SYSDATE senza ora frazionaria
    sql = re.sub(r"(?i)\bCURRENT_TIMESTAMP\b", "LOCALTIMESTAMP(0)", sql)
    # USER Oracle -> maiuscolo come fa Oracle
    sql = re.sub(r"(?i)(^SELECT\s+)user\s*$", r"\1UPPER(user)", sql)
    sql = re.sub(r"(?i)(^SELECT\s+)user\s*(,)", r"\1UPPER(user)\2", sql)
    return sql


class TranslationError(Exception):
    pass


def translate_sql(sql: str) -> str:
    """Traduce una query/DML/DDL Oracle in SQL PostgreSQL."""
    stripped = sql.strip().rstrip(";").strip()
    transformed = pre_rules(stripped)
    try:
        pg = sqlglot.transpile(transformed, read="oracle", write="postgres",
                               pretty=False)[0]
    except Exception as e:
        raise TranslationError(f"traduzione non riuscita: {e}") from e
    pg = post_rules(pg)
    return pg


# ---------------------------------------------------------------------------
# PL/SQL semplificato
# ---------------------------------------------------------------------------
def split_statements(body: str) -> list[str]:
    """Splitta su ';' rispettando stringhe e commenti."""
    out, buf = [], []
    i, n = 0, len(body)
    while i < n:
        ch = body[i]
        if ch == "'":
            buf.append(ch)
            i += 1
            while i < n:
                buf.append(body[i])
                if body[i] == "'":
                    if i + 1 < n and body[i + 1] == "'":
                        buf.append("'")
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
        elif body[i:i + 2] == "--":
            j = body.find("\n", i)
            j = n if j < 0 else j
            buf.append(body[i:j])
            i = j
        elif body[i:i + 2] == "/*":
            j = body.find("*/", i)
            j = n if j < 0 else j + 2
            buf.append(body[i:j])
            i = j
        elif ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
            i += 1
        else:
            buf.append(ch)
            i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


class PlsqlBlock:
    """Rappresentazione semplificata di un blocco PL/SQL anonimo."""

    def __init__(self, source: str):
        self.source = source.strip().rstrip(";").strip()
        self.supported = False
        self.error = None
        self.statements: list[str] = []          # chiamate pure
        self.assignments: list[tuple[str, str]] = []  # (BIND, expr)
        self.exception_other = False             # presente WHEN OTHERS
        self.handler_statements: list[str] = []
        self.handler_assignments: list[tuple[str, str]] = []
        self._parse()

    def _parse(self):
        src = self.source
        m = re.match(r"(?is)^DECLARE\b", src)
        if m:
            self.error = "sezione DECLARE non supportata"
            return
        m = re.match(r"(?is)^BEGIN\b(.*)$", src, re.S)
        if not m:
            self.error = "blocco non riconosciuto"
            return
        body = m.group(1)
        em = re.search(r"(?is)\bEXCEPTION\b(.*)$", body)
        handler = None
        if em:
            handler = em.group(1)
            if not re.search(r"(?i)WHEN\s+OTHERS", handler):
                self.error = "solo WHEN OTHERS e' supportato"
                return
            self.exception_other = True
            body = body[:em.start()]

        def _collect(src: str, into_statements, into_assignments) -> bool:
            """Ritorna False se contiene costrutti non supportati."""
            for stmt in split_statements(src):
                u = stmt.upper()
                if u.startswith(("DECLARE", "FOR ", "IF ", "WHILE", "OPEN ",
                                 "CLOSE ", "FETCH ", "EXIT", "NULL",
                                 "TYPE ", "SELECT ")):
                    return False
                am = re.match(r"^:(\w+)\s*:?=\s*(.+)$", stmt, re.S)
                if am:
                    into_assignments.append((am.group(1).upper(),
                                             am.group(2)))
                    continue
                into_statements.append(stmt)
            return True

        # rimuove END finale e raccoglie il body
        body = re.sub(r"(?is)\bEND\s*$", "", body).strip()
        if not body:
            self.error = "blocco vuoto"
            return
        if not _collect(body, self.statements, self.assignments):
            self.error = "costrutto PL/SQL non supportato nel body"
            return
        # handler WHEN OTHERS: assegnamenti con SQLCODE/SQLERRM sostituiti
        # a runtime dall'errore catturato
        if handler is not None:
            handler = re.sub(r"(?is)WHEN\s+OTHERS\s+THEN", "", handler)
            handler = re.sub(r"(?is)\bEND\s*$", "", handler).strip()
            if not _collect(handler, self.handler_statements,
                            self.handler_assignments):
                self.error = "costrutto non supportato nell'handler"
                return
        self.supported = True

    def translate(self) -> dict:
        """Ritorna {'calls': [sql], 'select': sql, 'assignments': {...}}.

        Le espressioni sono tradotte con sqlglot; i placeholder :BIND
        diventano %(BIND)s DOPO la traduzione (sqlglot non digerisce i
        placeholder psycopg).
        """
        calls = []
        for stmt in self.statements:
            pg = translate_sql("SELECT " + stmt)
            pg, _names = replace_bind_placeholders(pg)
            calls.append(pg)
        exprs = []
        for bind, expr in self.assignments:
            expr = expr.strip()
            # chiamata di funzione senza parentesi (sintassi PL/SQL)
            if re.fullmatch(r"[\w.$#]+", expr):
                expr = expr + "()"
            pg_expr = translate_sql("SELECT " + expr)
            pg_expr = re.sub(r"(?is)^SELECT\s+", "", pg_expr, count=1)
            pg_expr, _ = replace_bind_placeholders(pg_expr)
            exprs.append(f"({pg_expr})")
        final_select = f"SELECT {', '.join(exprs)}" if exprs else ""
        return {"calls": calls, "select": final_select,
                "assignment_order": [b for b, _ in self.assignments]}

    def translate_handler(self, error_num: int, error_msg: str) -> dict:
        """Traduce gli assegnamenti dell'handler WHEN OTHERS sostituendo
        SQLCODE/SQLERRM con i valori dell'errore catturato."""
        exprs = []
        order = []
        for bind, expr in self.handler_assignments:
            expr = re.sub(r"(?i)\bSQLCODE\b", str(-error_num), expr)
            expr = re.sub(r"(?i)\bSQLERRM\b", f"'{error_msg}'", expr)
            expr = expr.strip()
            if re.fullmatch(r"[\w.$#]+", expr):
                expr = expr + "()"
            pg_expr = translate_sql("SELECT " + expr)
            pg_expr = re.sub(r"(?is)^SELECT\s+", "", pg_expr, count=1)
            pg_expr, _ = replace_bind_placeholders(pg_expr)
            exprs.append(f"({pg_expr})")
            order.append(bind)
        final_select = f"SELECT {', '.join(exprs)}" if exprs else ""
        return {"select": final_select, "assignment_order": order}
