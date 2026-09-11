"""TNS layer: TCP packet framing.

Formats deduced from python-oracledb thin (impl/thin/packet.pyx,
transport.pyx, messages/connect.pyx).

Header (8 bytes):
  protocol < 315 : [len u16][cksum u16][type u8][flags u8][reserved u16]
  protocol >=315 : [len u32]          [type u8][flags u8][reserved u16]
DATA packets add 2 bytes of data_flags after the header.
Before the ACCEPT the 16-bit layout is always used.
"""
import struct

# packet types
PACKET_TYPE_CONNECT = 1
PACKET_TYPE_ACCEPT = 2
PACKET_TYPE_REFUSE = 4
PACKET_TYPE_REDIRECT = 5
PACKET_TYPE_DATA = 6
PACKET_TYPE_MARKER = 12
PACKET_TYPE_CONTROL = 14

# data flags
DATA_FLAGS_END_OF_REQUEST = 0x800

# marker types
MARKER_BREAK = 1
MARKER_RESET = 2
MARKER_INTERRUPT = 3

PROTOCOL_VERSION = 315          # 12.1: il minimo accettato dal client
SDU_SIZE = 8192

HEADER_SIZE = 8


class TnsPacket:
    __slots__ = ("ptype", "flags", "payload", "data_flags")

    def __init__(self, ptype: int, payload: bytes, flags: int = 0,
                 data_flags: int = 0):
        self.ptype = ptype
        self.flags = flags
        self.payload = payload
        self.data_flags = data_flags

    def __repr__(self):
        return (f"TnsPacket(type={self.ptype}, flags={self.flags:#x}, "
                f"data_flags={self.data_flags:#x}, len={len(self.payload)})")


async def read_packet(rdr, use_32bit: bool = False) -> TnsPacket | None:
    """Read a TNS packet from an async reader via await rdr.read_exact(n).

    use_32bit=False: 16-bit layout (used by the client before the ACCEPT);
    True: 32-bit length layout (protocol >= 315, post-ACCEPT).
    """
    header = await rdr.read_exact(HEADER_SIZE)
    if header is None:
        return None
    if use_32bit:
        length = struct.unpack(">I", header[0:4])[0]
    else:
        length = struct.unpack(">H", header[0:2])[0]
    ptype = header[4]
    flags = header[5]
    payload_len = length - HEADER_SIZE
    if payload_len < 0:
        payload_len = 0
    payload = await rdr.read_exact(payload_len) if payload_len else b""
    data_flags = 0
    if ptype == PACKET_TYPE_DATA and payload:
        data_flags = struct.unpack(">H", payload[0:2])[0]
        payload = payload[2:]
    return TnsPacket(ptype, payload, flags, data_flags)


def build_packet(ptype: int, payload: bytes, flags: int = 0,
                 use_32bit: bool = True) -> bytes:
    if use_32bit:
        total = HEADER_SIZE + len(payload)
        header = struct.pack(">IBBH", total, ptype, flags, 0)
    else:
        # [len u16][cksum u16][type u8][flags u8][reserved u16] = 8 byte
        total = HEADER_SIZE + len(payload)
        header = struct.pack(">HHBBH", total, 0, ptype, flags, 0)
    return header + payload


def build_data_packet(ttc_payload: bytes, data_flags: int = 0,
                      use_32bit: bool = True) -> bytes:
    payload = struct.pack(">H", data_flags) + ttc_payload
    return build_packet(PACKET_TYPE_DATA, payload, 0, use_32bit)


def build_accept_packet() -> bytes:
    """ACCEPT aligned with the real format observed on Oracle 26ai:
    version 319, options=1, flags2=0 (no FAST_AUTH / END_OF_RESPONSE /
    OOB check, so the client takes the simple paths)."""
    out = bytearray()
    out += struct.pack(">H", 319)                # version
    out += struct.pack(">H", 1)                  # options (GSO_DONT_CARE)
    out += b"\x00" * 10                          # skipped
    out += b"\x00"                               # flags1 (NSI): 0 = ok
    out += b"\x00" * 9                           # skipped
    out += struct.pack(">I", SDU_SIZE)           # SDU
    out += b"\x00" * 5                           # skipped (ver >= 318)
    out += struct.pack(">I", 0)                  # flags2
    return build_packet(PACKET_TYPE_ACCEPT, bytes(out), 0, use_32bit=False)


def build_refuse_packet(message: str) -> bytes:
    out = struct.pack(">H", 0) + struct.pack(">H", len(message)) + \
        message.encode()
    return build_packet(PACKET_TYPE_REFUSE, out, 0, use_32bit=False)


def build_marker_packet(marker_type: int) -> bytes:
    return build_packet(PACKET_TYPE_MARKER,
                        bytes([1, 0, marker_type]), 0, use_32bit=True)


def parse_connect_payload(payload: bytes) -> dict:
    """Parse the payload of the client CONNECT packet."""
    info = {}
    if len(payload) < 74:
        info["connect_string"] = ""
        return info
    (version_desired, version_min, service_options, sdu1, sdu2,
     proto_chars, line_turnaround, one, connect_string_len,
     data_offset) = struct.unpack(">10H", payload[0:20])
    info.update(version_desired=version_desired, version_min=version_min,
                service_options=service_options, sdu=sdu1,
                connect_string_len=connect_string_len)
    if connect_string_len:
        start = data_offset if data_offset else 74
        info["connect_string"] = payload[start:start + connect_string_len]\
            .decode("utf-8", "replace")
    else:
        info["connect_string"] = ""
    return info
