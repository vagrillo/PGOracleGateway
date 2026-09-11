# OracleBridge — test environment

Standalone environment to develop and verify the **OracleBridge** proxy:
a layer that presents itself to applications as **Oracle Database 26ai**
(SQL*Net/TNS protocol) and translates in real time to **PostgreSQL**.

## Components

| Component | Technology | Host port | Credentials |
|---|---|---|---|
| Reference Oracle | `container-registry.oracle.com/database/free:latest` (**26ai Free**, internal RU 23.26.3) | 1521 / FREEPDB1 | `system`/`SysOracle_26ai`, app: `TESTAPP`/`TestApp_26ai` |
| Target PostgreSQL | `postgres:17` + **orafce** (local build in `docker/postgres/`) | 5433 / `orabridge` | `testapp`/`TestApp_26ai` |
| Proxy (the deliverable) | OracleBridge | 1527 / FREEPDB1 | `TESTAPP`/`TestApp_26ai` |

Note on the Oracle image: the official `database/free` registry has no
versioned "26" tags yet; `latest` is the current 26ai Free (build RDBMS_23.26.3,
July 2026). First startup creates the database: **10-20 minutes**, be patient
(last log lines: `DATABASE IS READY TO USE!`). A faster alternative for later
iterations: `gvenzl/oracle-free:23-slim-faststart` (same RU engine, ~2 min start).

`vendor/ora2pg/` contains the [ora2pg](https://github.com/darold/ora2pg) clone,
used as a reference for schema/SQL conversion rules (see
`vendor/ora2pg/lib/Ora2Pg.pm` and the docs in `vendor/ora2pg/doc/`);
fetch it with `git clone https://github.com/darold/ora2pg vendor/ora2pg`.

## Requirements

- Working Docker on WSL (`docker ps` works without sudo, `docker` group)
- Python 3.12+ with: `python-oracledb`, `psycopg[binary]`, `sqlglot`
  (see `scripts/requirements.txt`; in this environment `python-oracledb`
  must be installed from the GitHub source because PyPI filters the package)

## Usage

```bash
cd test/
./up.sh                                  # bring everything up and run the suite
python3 scripts/smoke_test.py --mode oracle    # baseline (regenerable)
python3 scripts/smoke_test.py --mode postgres  # translation diagnostics
python3 scripts/smoke_test.py --mode proxy     # proxy verification
python3 scripts/smoke_test.py --mode oracle --filter ora.   # subset
```

`setup_oracle.py` and `setup_postgres.py` are idempotent: they recreate the
schema from scratch (also useful to reset sequences before a new baseline).
Note: the `postgres` mode executes DML with autocommit and **mutates the
mirror**: rerun `setup_postgres.py` after it (the `up.sh` script already
does, in the right order).

## Smoke test suite — the "Oracle contract"

`scripts/testcases.py` defines ~75 cases that an Oracle application expects
and that the proxy must reproduce identically:

- **sanity**: DUAL, USER, SYSDATE, SYS_GUID, `/*+ */` hints
- **functions**: NVL/NVL2/DECODE, TO_DATE/TO_CHAR, ADD_MONTHS, LISTAGG,
  stored function in SELECT, date arithmetic
- **types**: NUMBER, VARCHAR2/CHAR (padding), DATE vs TIMESTAMP, RAW, CLOB,
  BLOB, INTERVAL, empty string = NULL, implicit coercions
- **sequences**: `.NEXTVAL`/`.CURRVAL`, DEFAULT column
- **queries**: ROWNUM, classic pagination, `(+)` outer join, MINUS,
  CONNECT BY, ROLLUP, analytic functions, synonyms, FETCH FIRST
- **dml**: bind variables, MERGE, `RETURNING INTO`, ROLLBACK/SAVEPOINT
- **plsql**: anonymous blocks with OUT binds, package session state,
  REF CURSOR, EXCEPTION/SQLERRM/SQLCODE, DBMS_OUTPUT, triggers
- **errors**: ORA-00001/01400/00942/00904/01722/01476/00900 codes
  (the proxy must return the same ORA codes)

The `expect_rows` expectations are deterministic (no raw SYSDATE).

## Modes

1. **oracle** — runs everything on Oracle 26ai Free, saves
   `results/baseline_oracle.json` and `results/report_oracle.md`. This is
   the reference truth.
2. **postgres** — diagnostics: translates each query with **sqlglot**
   (Oracle→Postgres) or a manual override (`pg_sql`), runs it on
   PostgreSQL+orafce and compares with the baseline. The report shows the
   applied translations and where PostgreSQL diverges (e.g. `''` vs NULL,
   package state). This mode measures **how much translation work the
   proxy must do**.
3. **proxy** — same protocol as `oracle` but pointing at the proxy
   (localhost:1527): every test must result in `MATCH` against the baseline.

## Environment notes (WSL)

- `/dev/shm` >= 2GB required by Oracle: this WSL has 3.9G, ok
- images and volumes live in the WSL filesystem (ext4), not on /mnt/c
- PyPI on this host filters `python-oracledb`: install from GitHub
  `pip install https://github.com/oracle/python-oracledb/archive/refs/tags/v26.0.0.tar.gz`
  does NOT work (the ODPI submodule is missing): use
  `git clone --recurse-submodules --depth 1 -b v26.0.0 https://github.com/oracle/python-oracledb && pip install ./python-oracledb`
