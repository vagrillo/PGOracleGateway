"""Server TCP asyncio del proxy OracleBridge."""
import asyncio
import os
import struct
import sys

from . import tns
from .errors import OrabridgeError
from .ttc import Session


class _SocketReader:
    """Adattatore con read_exact (sincrono in firma, preleva dal buffer)."""

    def __init__(self, reader: asyncio.StreamReader):
        self.reader = reader
        self._buf = b""

    async def read_exact(self, n: int) -> bytes | None:
        while len(self._buf) < n:
            try:
                data = await self.reader.read(65536)
            except (ConnectionResetError, asyncio.IncompleteReadError):
                return None
            if not data:
                return None
            self._buf += data
        out, self._buf = self._buf[:n], self._buf[n:]
        import sys
        if os.environ.get('OB_DUMP'):
            print('[raw]', n, out[:48].hex(), file=sys.stderr, flush=True)
        return out


class ProxyServer:
    def __init__(self, listen_host: str, listen_port: int,
                 pg_host: str, pg_port: int, pg_db: str,
                 known_password: str | None = None, verbose: bool = False):
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.pg_host = pg_host
        self.pg_port = pg_port
        self.pg_db = pg_db
        self.known_password = known_password
        self.verbose = verbose

    def _log(self, *args):
        if self.verbose:
            import sys
            print("[proxy]", *args, file=sys.stderr, flush=True)

    async def handle_client(self, reader: asyncio.StreamReader,
                            writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        self._log("connessione da", peer)
        rdr = _SocketReader(reader)
        session = None
        try:
            # ---- handshake TNS: CONNECT (16 bit) -> ACCEPT ----
            packet = await tns.read_packet(rdr, use_32bit=False)
            if packet is None or packet.ptype != tns.PACKET_TYPE_CONNECT:
                self._log("primo pacchetto non CONNECT:", packet)
                return
            info = tns.parse_connect_payload(packet.payload)
            self._log("CONNECT:", info.get("connect_string", "")[:120])
            writer.write(tns.build_accept_packet())
            await writer.drain()

            # ---- loop TTC (framing 32 bit) ----
            session = Session(self.pg_host, self.pg_port, self.pg_db,
                              log=self._log)
            session.known_password = self.known_password
            while True:
                packet = await tns.read_packet(rdr, use_32bit=True)
                if packet is None:
                    self._log("client disconnesso")
                    break
                self._log("pkt:", repr(packet))
                if packet.ptype == tns.PACKET_TYPE_MARKER:
                    marker = packet.payload[2] if len(packet.payload) > 2 else 0
                    self._log("marker ricevuto:", marker)
                    writer.write(tns.build_marker_packet(tns.MARKER_RESET))
                    await writer.drain()
                    if marker == tns.MARKER_RESET:
                        # dopo il reset il client attende l'error packet
                        # di chiusura prima di ri-sollevare la sua eccezione
                        err = session._error_message(
                            1013, "ORA-01013: user requested cancel of "
                                  "current operation", 0, 0, with_params=False)
                        writer.write(tns.build_data_packet(err))
                        await writer.drain()
                    continue
                if packet.ptype == tns.PACKET_TYPE_CONTROL:
                    self._log("control packet ignorato")
                    continue
                if packet.ptype != tns.PACKET_TYPE_DATA:
                    self._log("pacchetto non gestito:", packet)
                    continue
                response = session.handle_ttc(packet.payload)
                if response is None:
                    continue
                if os.environ.get("OB_DUMP"):
                    print(f"[resp] {len(response)}B {response[:300].hex()}",
                          file=sys.stderr, flush=True)
                for chunk in self._chunks(response):
                    writer.write(tns.build_data_packet(chunk))
                await writer.drain()
                if session.pg is not None and session.pg.conn is None:
                    break
        except (ConnectionResetError, BrokenPipeError):
            self._log("connessione interrotta")
        except Exception as e:  # noqa: BLE001
            self._log("errore sessione:", type(e).__name__, e)
        finally:
            if session is not None and session.pg is not None:
                session.pg.close()
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    @staticmethod
    def _chunks(data: bytes, size: int = tns.SDU_SIZE - 16):
        for i in range(0, len(data), size):
            yield data[i:i + size]

    async def serve(self):
        server = await asyncio.start_server(self.handle_client,
                                            self.listen_host,
                                            self.listen_port)
        addrs = ", ".join(str(sock.getsockname()) for sock in server.sockets)
        print(f"OracleBridge proxy in ascolto su {addrs} "
              f"(backend {self.pg_host}:{self.pg_port}/{self.pg_db})",
              flush=True)
        async with server:
            await server.serve_forever()
