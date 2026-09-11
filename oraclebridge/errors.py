"""Codici e messaggi di errore ORA + mapping SQLSTATE PostgreSQL -> ORA."""
import re

# SQLSTATE PG -> (numero ORA, template messaggio)
SQLSTATE_TO_ORA = {
    "23505": (1, "unique constraint ({constraint}) violated"),
    "23502": (1400, "cannot insert NULL into ({column})"),
    "23503": (2291, "integrity constraint violated - parent key not found"),
    "42P01": (942, "table or view does not exist"),
    "42703": (904, "invalid identifier"),
    "22P02": (1722, "invalid number"),
    "22012": (1476, "divisor is equal to zero"),
    "42601": (900, "invalid SQL statement"),
    "42P07": (955, "name is already used by an existing object"),
    "42883": (904, "invalid identifier"),
    "22001": (12899, "value too large for column"),
    "23514": (2290, "check constraint violated"),
    "28000": (1017, "invalid username/password; logon denied"),
    "28P01": (1017, "invalid username/password; logon denied"),
    "3D000": (942, "schema does not exist"),
}

ORA_MESSAGES = {
    0: "",
    1: "ORA-00001: unique constraint (%s) violated",
    14: "ORA-00014: session duplicate",
    900: "ORA-00900: invalid SQL statement",
    904: "ORA-00904: %s: invalid identifier",
    905: "ORA-00905: missing keyword",
    911: "ORA-00911: invalid character",
    913: "ORA-00913: too many values",
    917: "ORA-00917: missing comma",
    932: "ORA-00932: inconsistent datatypes",
    936: "ORA-00936: missing expression",
    942: "ORA-00942: table or view does not exist",
    959: "ORA-00959: tablespace does not exist",
    1017: "ORA-01017: invalid username/password; logon denied",
    1045: "ORA-01045: user lacks CREATE SESSION privilege",
    1400: "ORA-01400: cannot insert NULL into (%s)",
    1403: "ORA-01403: no data found",
    1404: "ORA-01404: ALTER COLUMN will make an index too large",
    1405: "ORA-01405: fetched column value is NULL",
    1406: "ORA-01406: fetched column value was truncated",
    1407: "ORA-01407: cannot update (%s) to NULL",
    1438: "ORA-01438: value larger than specified precision allowed",
    1476: "ORA-01476: divisor is equal to zero",
    1722: "ORA-01722: invalid number",
    1747: "ORA-01747: invalid user.table.column identifier",
    1830: "ORA-01830: date format picture ends before converting input",
    2291: "ORA-02291: integrity constraint violated - parent key not found",
    2292: "ORA-02292: integrity constraint violated - child record found",
    2290: "ORA-02290: check constraint violated",
    6502: "ORA-06502: PL/SQL: numeric or value error",
    6550: "ORA-06550: line %s, column %s:\nPLS-00103: %s",
    12514: "ORA-12514: TNS:listener does not currently know of service",
    12899: "ORA-12899: value too large for column %s",
}


class OrabridgeError(Exception):
    """Errore tradotto in risposta TTC ORA."""

    def __init__(self, num: int, message: str = "", pos: int = 0):
        self.num = num
        self.message = message or ORA_MESSAGES.get(num, f"ORA-{num:05d}")
        if "%s" in self.message and message:
            pass
        self.pos = pos
        super().__init__(self.message)


def ora_message(num: int, detail="") -> str:
    template = ORA_MESSAGES.get(num, f"ORA-{num:05d}")
    if template and "%s" in template:
        if isinstance(detail, tuple):
            return template % detail
        return template % (detail if detail else "???",)
    return template


def from_pg_error(pg_error) -> OrabridgeError:
    """Converte un errore psycopg in OrabridgeError."""
    sqlstate = getattr(pg_error, "sqlstate", None) or "HY000"
    if sqlstate in SQLSTATE_TO_ORA:
        num, template = SQLSTATE_TO_ORA[sqlstate]
        detail = ""
        if "%s" in template:
            # estrae l'ultimo identificatore quotato dal messaggio PG
            # es. 'duplicate key value violates unique constraint "pk_dept"'
            quoted = re.findall(r'"([^"]+)"', str(pg_error))
            detail = quoted[-1].upper() if quoted else \
                str(pg_error).split("\n")[0][:60]
        return OrabridgeError(num, ora_message(num, detail))
    # fallback: errore generico con testo PG
    first_line = str(pg_error).split("\n")[0]
    return OrabridgeError(20000, f"ORA-20000: [pg-{sqlstate}] {first_line}")
