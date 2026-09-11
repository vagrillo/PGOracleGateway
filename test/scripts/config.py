"""Centralized configuration of the OracleBridge test environments.

All values are overridable via environment variables (OB_ prefix).
"""
import os
from dataclasses import dataclass


def _get(name: str, default: str) -> str:
    return os.environ.get(f"OB_{name}", default)


@dataclass(frozen=True)
class OracleCfg:
    host: str = _get("ORA_HOST", "localhost")
    port: int = int(_get("ORA_PORT", "1521"))
    service: str = _get("ORA_SERVICE", "FREEPDB1")
    user: str = _get("ORA_USER", "testapp")
    password: str = _get("ORA_PASSWORD", "TestApp_26ai")
    sys_password: str = _get("ORA_SYS_PASSWORD", "SysOracle_26ai")

    @property
    def dsn(self) -> str:
        return f"{self.host}:{self.port}/{self.service}"


@dataclass(frozen=True)
class PostgresCfg:
    host: str = _get("PG_HOST", "localhost")
    port: int = int(_get("PG_PORT", "5433"))
    dbname: str = _get("PG_DB", "orabridge")
    user: str = _get("PG_USER", "testapp")
    password: str = _get("PG_PASSWORD", "TestApp_26ai")


@dataclass(frozen=True)
class ProxyCfg:
    """OracleBridge proxy endpoint (to be implemented): pretends to be Oracle."""
    host: str = _get("PROXY_HOST", "localhost")
    port: int = int(_get("PROXY_PORT", "1527"))
    service: str = _get("PROXY_SERVICE", "FREEPDB1")
    user: str = _get("PROXY_USER", "testapp")
    password: str = _get("PROXY_PASSWORD", "TestApp_26ai")

    @property
    def dsn(self) -> str:
        return f"{self.host}:{self.port}/{self.service}"


ORACLE = OracleCfg()
POSTGRES = PostgresCfg()
PROXY = ProxyCfg()
RESULTS_DIR = os.environ.get("OB_RESULTS_DIR",
                             os.path.join(os.path.dirname(__file__), "..", "results"))
