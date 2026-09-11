"""Conversioni di tipo Oracle <-> Python/PostgreSQL.

Encoder lato server (valori verso il client) e decoder lato server (bind
in ingresso dal client). Algoritmi specchio di impl/base/encoders.pyx e
decoders.pyx di python-oracledb.
"""
import datetime
from decimal import Decimal, InvalidOperation

NUMBER_AS_TEXT_CHARS = 172
NUMBER_MAX_DIGITS = 40
DURATION_MID = 0x80000000
DURATION_OFFSET = 60

ORA_TYPE_VARCHAR = 1
ORA_TYPE_NUMBER = 2
ORA_TYPE_LONG = 8
ORA_TYPE_DATE = 12
ORA_TYPE_RAW = 23
ORA_TYPE_CHAR = 96
ORA_TYPE_CURSOR = 102
ORA_TYPE_TIMESTAMP = 180
ORA_TYPE_TIMESTAMP_TZ = 181
ORA_TYPE_INTERVAL_DS = 183
ORA_TYPE_BLOB = 113
ORA_TYPE_CLOB = 112


# ---------------------------------------------------------------------------
# NUMBER: formato canonico Oracle (esponente + coppie base-100)
# ---------------------------------------------------------------------------
def encode_number(value) -> bytes:
    """Codifica un valore numerico nel formato binario Oracle NUMBER.

    Replica passo-passo l'algoritmo del client (impl/base/encoders.pyx,
    encode_number), che parte dalla rappresentazione testuale del numero.
    Verificato con DUMP() su Oracle 26ai: 1=c1 02, 10=c1 0b, 100=c2 02,
    123.45=c2 02 18 2e, -1=3e 64 66, 0.001=bf 0b.
    """
    if isinstance(value, bytes):
        value = value.decode()
    if isinstance(value, float):
        value = repr(value)
    elif not isinstance(value, str):
        value = str(value)
    text = value.strip()
    if text.startswith("-"):
        is_negative = True
        text = text[1:]
    else:
        is_negative = False
        text = text.lstrip("+")
    if not text:
        raise ValueError(f"numero vuoto: {value!r}")

    digits: list[int] = []
    # parte intera: gli zero iniziali non contano
    pos = 0
    while pos < len(text) and text[pos] not in ".eE":
        ch = text[pos]
        if not ch.isdigit():
            raise ValueError(f"numero invalido: {value!r}")
        d = int(ch)
        pos += 1
        if d == 0 and not digits:
            continue
        digits.append(d)
    dpi = len(digits)

    # parte frazionaria: gli zero iniziali prima della prima cifra
    # significativa scalano l'indice decimale verso il basso
    if pos < len(text) and text[pos] == ".":
        pos += 1
        while pos < len(text) and text[pos] not in "eE":
            ch = text[pos]
            if not ch.isdigit():
                raise ValueError(f"numero invalido: {value!r}")
            d = int(ch)
            pos += 1
            if d == 0 and not digits:
                dpi -= 1
                continue
            digits.append(d)

    # esponente
    if pos < len(text) and text[pos] in "eE":
        pos += 1
        exp_neg = False
        if pos < len(text) and text[pos] in "+-":
            exp_neg = text[pos] == "-"
            pos += 1
        if pos >= len(text):
            raise ValueError(f"esponente vuoto: {value!r}")
        exp_value = int(text[pos:])
        dpi += -exp_value if exp_neg else exp_value

    # zero finali non significativi
    while digits and digits[-1] == 0:
        digits.pop()
    if not digits:
        return b"\x80"

    if len(digits) > 40 or dpi > 126 or dpi < -129:
        raise ValueError(f"numero fuori range Oracle: {value!r}")

    # dpi dispari: primo coppia con una sola cifra (prefisso zero implicito)
    prepend_zero = False
    if dpi % 2 == 1:
        prepend_zero = True
        if digits:
            digits.append(0)
            dpi += 1
    if len(digits) % 2 == 1:
        digits.append(0)

    num_pairs = len(digits) // 2
    # divisione intera con troncamento verso zero (semantica C)
    exponent_on_wire = int(dpi / 2) + 192
    if is_negative:
        exponent_on_wire = ~exponent_on_wire & 0xFF
    out = bytearray([exponent_on_wire])
    dp = 0
    for i in range(num_pairs):
        if i == 0 and prepend_zero:
            d = digits[dp]
            dp += 1
        else:
            d = digits[dp] * 10 + digits[dp + 1]
            dp += 2
        out.append(101 - d if is_negative else d + 1)
    if is_negative and len(digits) < 40:
        out.append(102)
    return bytes(out)


def decode_number(data: bytes) -> Decimal:
    """Decodifica il formato binario Oracle NUMBER in Decimal.

    Invariante dell'algoritmo del client: per il segno positivo,
    valore = int(cifre) * 10^(2*(e_wire-192) - 2*n_coppie), con esponente
    e_wire = byte0 e cifre = coppie base-100 (byte-1). Per il negativo:
    complemento a uno dell'esponente e delle cifre (101-byte), terminatore 102.
    """
    if not data:
        return Decimal(0)
    if data[0] == 0x80:
        return Decimal(0)
    if data[0] & 0x80:
        e_wire = data[0]
        pairs = [b - 1 for b in data[1:]]
        is_negative = False
    else:
        e_wire = (~data[0]) & 0xFF
        raw = data[1:]
        if raw.endswith(b"\x66"):
            raw = raw[:-1]
        pairs = bytes(101 - b for b in raw)
        is_negative = True
    if not pairs:
        return Decimal(0)
    if any(p < 0 or p > 99 for p in pairs):
        raise ValueError(f"NUMBER malformato: {data.hex()}")
    digit_str = "".join(f"{p:02d}" for p in pairs)
    exponent = 2 * (e_wire - 192 - len(pairs))
    value = Decimal(digit_str).scaleb(exponent)
    return -value if is_negative else value


# ---------------------------------------------------------------------------
# DATE / TIMESTAMP
# ---------------------------------------------------------------------------
def encode_date(value: datetime.datetime) -> bytes:
    year = value.year
    return bytes([(year // 100) + 100, (year % 100) + 100,
                  value.month, value.day,
                  value.hour + 1, value.minute + 1, value.second + 1])


def encode_timestamp(value: datetime.datetime, with_tz: bool = False) -> bytes:
    out = bytearray(encode_date(value))
    out += (value.microsecond * 1000).to_bytes(4, "big")
    if with_tz:
        # compatibile con la convenzione del client (offset fittizi 20/60)
        out.append(20)
        out.append(60)
    return bytes(out)


def decode_date(data: bytes) -> datetime.datetime:
    if len(data) < 7:
        raise ValueError(f"Oracle DATE malformato: {data.hex()}")
    year = (data[0] - 100) * 100 + (data[1] - 100)
    return datetime.datetime(year, data[2], data[3],
                             data[4] - 1, data[5] - 1, data[6] - 1)


def decode_timestamp(data: bytes) -> datetime.datetime:
    base = decode_date(data[:7])
    if len(data) >= 11:
        fseconds = int.from_bytes(data[7:11], "big")
        return base.replace(microsecond=fseconds // 1000)
    return base


# ---------------------------------------------------------------------------
# INTERVAL DAY TO SECOND
# ---------------------------------------------------------------------------
def encode_interval_ds(days: int, hours: int, minutes: int, seconds: int,
                       fseconds: int) -> bytes:
    out = bytearray()
    out += ((days + DURATION_MID) & 0xFFFFFFFF).to_bytes(4, "big")
    out.append(hours + DURATION_OFFSET)
    out.append(minutes + DURATION_OFFSET)
    out.append(seconds + DURATION_OFFSET)
    out += ((fseconds + DURATION_MID) & 0xFFFFFFFF).to_bytes(4, "big")
    return bytes(out)


def decode_interval_ds(data: bytes):
    days = int.from_bytes(data[0:4], "big") - DURATION_MID
    hours = data[4] - DURATION_OFFSET
    minutes = data[5] - DURATION_OFFSET
    seconds = data[6] - DURATION_OFFSET
    fseconds = int.from_bytes(data[7:11], "big") - DURATION_MID
    return datetime.timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
        microseconds=abs(fseconds) // 1000)


# ---------------------------------------------------------------------------
# Conversioni PG -> valori wire Oracle, in base al tipo dichiarato
# ---------------------------------------------------------------------------
def encode_column_value(ora_type: int, value) -> bytes | None:
    """Valore PG/Python -> bytes wire Oracle (senza prefisso lunghezza).

    Ritorna None per NULL.
    """
    if value is None:
        return None
    if ora_type == ORA_TYPE_NUMBER:
        return encode_number(value)
    if ora_type in (ORA_TYPE_VARCHAR, ORA_TYPE_CHAR, ORA_TYPE_LONG,
                    ORA_TYPE_CLOB):
        if isinstance(value, memoryview):
            value = value.tobytes()
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        if not isinstance(value, str):
            value = str(value)
        return value.encode("utf-8")
    if ora_type in (ORA_TYPE_RAW, ORA_TYPE_BLOB):
        if isinstance(value, memoryview):
            value = value.tobytes()
        if isinstance(value, str):
            value = value.encode("utf-8")
        return bytes(value)
    if ora_type == ORA_TYPE_DATE:
        return encode_date(value)
    if ora_type == ORA_TYPE_TIMESTAMP:
        return encode_timestamp(value)
    if ora_type in (ORA_TYPE_TIMESTAMP_TZ,):
        return encode_timestamp(value, with_tz=True)
    if ora_type == ORA_TYPE_INTERVAL_DS:
        td = value
        total_seconds = int(td.total_seconds())
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        fseconds = td.microseconds * 1000
        if td.days < 0:
            days, hours, minutes, seconds, fseconds = \
                -days, -hours, -minutes, -seconds, -fseconds
        return encode_interval_ds(days, hours, minutes, seconds, fseconds)
    raise ValueError(f"tipo Oracle non gestito in encode: {ora_type}")


ora_buffer_sizes = {
    ORA_TYPE_NUMBER: 22,
    ORA_TYPE_DATE: 7,
    ORA_TYPE_TIMESTAMP: 11,
    ORA_TYPE_TIMESTAMP_TZ: 13,
    ORA_TYPE_INTERVAL_DS: 11,
}
