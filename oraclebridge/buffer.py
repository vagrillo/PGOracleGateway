"""TTC read/write primitives.

Server-side mirror of the python-oracledb client primitives
(src/oracledb/impl/base/buffer.pyx).
"""
import struct
from decimal import Decimal


class TnsBufError(Exception):
    pass


def enc_varint(value: int, max_len: int) -> bytes:
    """Variable TTC integer (ub1/ub2/ub4/ub8): first byte = length,
    high bit = negative sign; zero -> single 0 byte."""
    if value is None:
        value = 0
    negative = value < 0
    if negative:
        value = -value
    if value == 0:
        return b"\x00"
    raw = value.to_bytes(max_len, "big").lstrip(b"\x00") or b"\x00"
    if negative:
        return bytes([len(raw) | 0x80]) + raw
    return bytes([len(raw)]) + raw


class TTCReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def bytes_left(self) -> int:
        return len(self.data) - self.pos

    def raw(self, n: int) -> bytes:
        if self.bytes_left() < n:
            raise TnsBufError(
                f"buffer underrun: requested {n}, available {self.bytes_left()}")
        out = self.data[self.pos:self.pos + n]
        self.pos += n
        return out

    def u8(self) -> int:
        return self.raw(1)[0]

    def u16be(self) -> int:
        return struct.unpack(">H", self.raw(2))[0]

    def u32be(self) -> int:
        return struct.unpack(">I", self.raw(4))[0]

    def u64be(self) -> int:
        return struct.unpack(">Q", self.raw(8))[0]

    def u16le(self) -> int:
        return struct.unpack("<H", self.raw(2))[0]

    def varint(self, max_len: int) -> int:
        first = self.u8()
        negative = bool(first & 0x80)
        length = first & 0x7F
        if length == 0:
            return 0
        if length > max_len:
            raise TnsBufError(f"TTC integer too long: {length}")
        value = int.from_bytes(self.raw(length), "big")
        return -value if negative else value

    def ub1(self) -> int:
        return self.varint(1)

    def ub2(self) -> int:
        return self.varint(2)

    def ub4(self) -> int:
        return self.varint(4)

    def ub8(self) -> int:
        return self.varint(8)

    def sb2(self) -> int:
        first = self.u8()
        negative = bool(first & 0x80)
        length = first & 0x7F
        if length == 0:
            return 0
        value = int.from_bytes(self.raw(length), "big")
        return -value if negative else value

    def sb4(self) -> int:
        first = self.u8()
        negative = bool(first & 0x80)
        length = first & 0x7F
        if length == 0:
            return 0
        value = int.from_bytes(self.raw(length), "big")
        return -value if negative else value

    def skip_ub(self, max_len: int) -> None:
        length = self.u8() & 0x7F
        if length:
            self.raw(length)

    def skip_ub2(self):
        self.skip_ub(2)

    def skip_ub4(self):
        self.skip_ub(4)

    def skip_ub8(self):
        self.skip_ub(8)

    # ---- length-prefixed bytes (ub1; 0/255 = NULL; 254 = chunked) ----
    def length_prefixed_bytes(self) -> bytes | None:
        length = self.u8()
        if length in (0, 255):
            return None
        if length == 254:  # TNS_LONG_LENGTH_INDICATOR
            chunks = bytearray()
            while True:
                n = self.u32be()
                if n == 0:
                    break
                chunks += self.raw(n)
            return bytes(chunks)
        return self.raw(length)

    def read_bytes(self) -> bytes | None:
        """client read_bytes() equivalent: ub1 length + data"""
        return self.length_prefixed_bytes()

    def read_bytes_with_length(self) -> bytes | None:
        """client read_bytes_with_length() equivalent: ub4 count, then bytes"""
        count = self.ub4()
        return self.read_bytes() if count > 0 else None

    def read_str(self) -> str | None:
        data = self.length_prefixed_bytes()
        return data.decode("utf-8") if data is not None else None

    def read_str_with_length(self) -> str | None:
        count = self.ub4()
        return self.read_str() if count > 0 else None

    def skip_bytes(self) -> None:
        if self.length_prefixed_bytes() is not None:
            pass

    def skip_bytes_with_length(self) -> None:
        if self.ub4() > 0:
            self.skip_bytes()


class TTCWriter:
    def __init__(self):
        self._parts: list[bytes] = []

    def getvalue(self) -> bytes:
        return b"".join(self._parts)

    def u8(self, v: int):
        self._parts.append(struct.pack("B", v & 0xFF))

    def u16be(self, v: int):
        self._parts.append(struct.pack(">H", v & 0xFFFF))

    def u32be(self, v: int):
        self._parts.append(struct.pack(">I", v & 0xFFFFFFFF))

    def u64be(self, v: int):
        self._parts.append(struct.pack(">Q", v & 0xFFFFFFFFFFFFFFFF))

    def u16le(self, v: int):
        self._parts.append(struct.pack("<H", v & 0xFFFF))

    def raw(self, data: bytes):
        self._parts.append(data)

    def varint(self, value: int, max_len: int):
        self._parts.append(enc_varint(value, max_len))

    def ub1(self, v):
        self.varint(v, 1)

    def ub2(self, v):
        self.varint(v, 2)

    def ub4(self, v):
        self.varint(v, 4)

    def ub8(self, v):
        self.varint(v, 8)

    def sb4(self, v):
        self.varint(v, 4)

    def sb2(self, v):
        self.varint(v, 2)

    def sb1(self, v):
        self._parts.append(struct.pack("b", max(-128, min(127, int(v)))))

    # ---- bytes con lunghezza ----
    def length_prefixed(self, data: bytes | None):
        if data is None or len(data) == 0:
            self.u8(0)
            return
        n = len(data)
        if n <= 252:
            self.u8(n)
            self.raw(data)
        else:
            self.u8(254)
            pos = 0
            while pos < n:
                chunk = data[pos:pos + 32767]
                pos += len(chunk)
                self.u32be(len(chunk))
                self.raw(chunk)
            self.u32be(0)

    def write_bytes(self, data: bytes):
        self.length_prefixed(data)

    def write_bytes_with_two_lengths(self, value):
        """ub4 count + ub1-length bytes (schema write_bytes_with_two_lengths)"""
        if value is None:
            self.ub4(0)
            return
        data = value if isinstance(value, bytes) else value.encode("utf-8")
        self.ub4(len(data))
        if data:
            self.length_prefixed(data)

    def write_str(self, value: str):
        self.length_prefixed(value.encode("utf-8"))
