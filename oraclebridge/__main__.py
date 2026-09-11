"""Avvio del proxy: python -m oraclebridge

Configurazione via variabili d'ambiente (prefisso OB_):
  OB_LISTEN_HOST (default 0.0.0.0)   OB_LISTEN_PORT (default 1527)
  OB_PG_HOST (default localhost)     OB_PG_PORT (default 5433)
  OB_PG_DB (default orabridge)
  OB_KNOWN_PASSWORD (opzionale: password Oracle attesa dal proxy; se vuota
  viene usata quella passata dal client direttamente verso PostgreSQL)
"""
import asyncio
import os
import sys

from .server import ProxyServer


def _get(name: str, default: str) -> str:
    return os.environ.get(f"OB_{name}", default)


def main():
    server = ProxyServer(
        listen_host=_get("LISTEN_HOST", "0.0.0.0"),
        listen_port=int(_get("LISTEN_PORT", "1527")),
        pg_host=_get("PG_HOST", "localhost"),
        pg_port=int(_get("PG_PORT", "5433")),
        pg_db=_get("PG_DB", "orabridge"),
        # l'O5LOGON 11g richiede la password attesa in configurazione: le
        # credenziali del client vengono comunque verificate e riusate per
        # aprire la sessione PostgreSQL (utente minuscolo)
        known_password=os.environ.get("OB_KNOWN_PASSWORD", "TestApp_26ai"),
        verbose=os.environ.get("OB_VERBOSE", "") not in ("", "0"),
    )
    try:
        asyncio.run(server.serve())
    except KeyboardInterrupt:
        print(" arresto", file=sys.stderr)


if __name__ == "__main__":
    main()
