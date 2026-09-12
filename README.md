# PGO Comet  - the PostgreSQL to Oracle Bridge !

A proxy that presents itself to applications as **Oracle Database**
(the proprietary SQL*Net/TNS protocol + TTC) and translates in real time to
**PostgreSQL**. The application uses the standard Oracle driver
(python-oracledb thin, and by extension any OCI client speaking the same TTC
dialect) without noticing the difference.

## Architecture

```
Oracle app ──TNS/TTC──▶ OracleBridge proxy ──translated SQL──▶ PostgreSQL
 (Oracle driver)        oraclebridge/                          (with orafce)
```

Components (`oraclebridge/`):

| Module | Role |
|---|---|
| `tns.py` | SQL*Net packet framing (16/32-bit headers, CONNECT/ACCEPT, markers, DATA) |
| `buffer.py` | TTC primitives (signed variable-length integers, length-prefixed strings, 254 chunking) |
| `types.py` | Oracle type encoder/decoder: canonical NUMBER, 7-byte DATE, TIMESTAMP, INTERVAL DS, RAW |
| `auth.py` | O5LOGON 11g verifier: sha1(password+salt) → AES-192, session key exchange, PBKDF2-SHA512 combo key |
| `translate.py` | Oracle→PostgreSQL engine: pre-rules ((+), ROWNUM, DUAL, sequences, DBMS_LOB, RAWTOHEX), sqlglot, post-rules; simplified PL/SQL |
| `pg.py` | Per-client PostgreSQL session (Oracle-like transaction, column metadata, OID→ORA type mapping) |
| `ttc.py` | TTC state machine: auth (118/115), execute (94), fetch (5), commit/rollback, describe/rows/io-vector/error responses |
| `server.py` | asyncio TCP server |

Protocol choices were verified against the python-oracledb thin sources
(`src/oracledb/impl/thin/*.pyx`, v26) and in the field against Oracle 26ai
Free:

- the server negotiates **field version 6** (11.2): simpler wire formats, no
  tokens / fast-auth / end-of-response → every response is terminated by an
  ERROR or STATUS message;
- the **DML rowcount** and the **cursor id** travel inside the ERROR(4)
  message with error number 0; end of rows is ERROR 1403 (swallowed by the
  client);
- authentication requires the expected password in configuration (11g O5LOGON
  already uses it in phase 1); the decrypted credentials open the PostgreSQL
  session (lowercased user).

## Usage

```bash
# test PostgreSQL backend (see test/)
cd test && docker compose -f docker/docker-compose.yml up -d

# proxy
OB_LISTEN_PORT=1527 OB_PG_PORT=5433 OB_KNOWN_PASSWORD=TestApp_26ai \
  python3 -m oraclebridge
```

The application connects to `localhost:1527/FREEPDB1` with
`testapp/TestApp_26ai` using the standard Oracle driver.

## Status (smoke tests, 75 cases)

- Oracle 26ai baseline: **75/75 PASS** (`test/`, `oracle` mode)
- through the proxy: **62/75 PASS**, automatic comparison vs baseline

Known gaps (documented, not regressions):

1. **Advanced PL/SQL** (pls.010-013, 008): DECLARE/FOR LOOP/explicit
   cursors/BULK COLLECT/DBMS_OUTPUT.CHARARR require a PL/SQL engine; the
   proxy supports blocks with calls, `:bind := expr` assignments,
   `raise_application_error` and `WHEN OTHERS` handlers with
   SQLCODE/SQLERRM.
2. **Oracle semantics not reproducible at SQL level**: `''` = NULL,
   `NEXTVAL` evaluated once per row, CHAR padding in `LENGTH`,
   `TRUNC(date)` arithmetic producing an interval in PostgreSQL.
3. **CONNECT BY** not translated yet (requires recursive CTE generation).
4. dml.006/007 in the full run: CLOSE_CURSORS piggyback interplay
   (statement cache full) to be refined.
5. LOB columns are served as VARCHAR2/RAW (max 32 KB) instead of LOB
   locators.

## Proxy development: chosen language = Python

`python-oracledb` thin mode is a pure-Python implementation of the client
side of the protocol: it was used as the executable specification to write
the server side (no public Oracle documentation exists). `sqlglot` covers the
SQL translation, `psycopg` the backend. For production throughput the
TNS/TTC layer can be ported to Go or Rust keeping the tests as the contract.




## the real PGO Comet !
<img width="756" height="720" alt="image" src="https://github.com/user-attachments/assets/f835ca4e-6ec3-4cd2-8849-b72db942be82" />
