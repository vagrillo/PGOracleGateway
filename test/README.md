# OracleBridge — ambiente di test

Ambiente standalone per sviluppare e verificare il proxy **OracleBridge**:
un layer che si presenta alle applicazioni come **Oracle Database 26ai**
(protocollo SQL*Net/TNS) e traduce in tempo reale verso **PostgreSQL**.

## Composizione

| Componente | Tecnologia | Porta host | Credenziali |
|---|---|---|---|
| Oracle di riferimento | `container-registry.oracle.com/database/free:latest` (**26ai Free**, RU interna 23.26.3) | 1521 / FREEPDB1 | `system`/`SysOracle_26ai`, app: `TESTAPP`/`TestApp_26ai` |
| PostgreSQL target | `postgres:17` + **orafce** (build locale `docker/postgres/`) | 5433 / `orabridge` | `testapp`/`TestApp_26ai` |
| Proxy (futuro) | OracleBridge | 1527 / FREEPDB1 | `TESTAPP`/`TestApp_26ai` |

Nota immagine Oracle: il registro ufficiale `database/free` non ha ancora tag
versionati "26"; `latest` e' la 26ai Free corrente (build RDBMS_23.26.3,
luglio 2026). Il primo avvio crea il database: **10-20 minuti**, pazientare
(gli ultimi log: `DATABASE IS READY TO USE!`). Alternativa piu' rapida per
iterazioni future: `gvenzl/oracle-free:23-slim-faststart` (stesso engine RU,
avvio ~2 min).

`vendor/ora2pg/` contiene il clone di [ora2pg](https://github.com/darold/ora2pg),
usato come riferimento per le regole di conversione schema/SQL
(vedi `vendor/ora2pg/lib/Ora2Pg.pm` e la documentazione in `vendor/ora2pg/doc/`).

## Requisiti

- Docker funzionante su WSL (`docker ps` funziona senza sudo, gruppo `docker`)
- Python 3.12+ con: `python-oracledb`, `psycopg[binary]`, `sqlglot`
  (vedi `scripts/requirements.txt`; in questo ambiente `python-oracledb`
  va installato da sorgente GitHub perché PyPI filtra il pacchetto)

## Uso

```bash
cd test/
./up.sh                                  # su tutto ed esegue la suite
python3 scripts/smoke_test.py --mode oracle    # baseline (rigenerabile)
python3 scripts/smoke_test.py --mode postgres  # diagnostica traduzione
python3 scripts/smoke_test.py --mode proxy     # verifica del proxy
python3 scripts/smoke_test.py --mode oracle --filter ora.   # subset
```

`setup_oracle.py` e `setup_postgres.py` sono idempotenti: ricreano lo schema
da zero (utile anche per azzerare le sequenze prima di una nuova baseline).

## Suite di smoke test — il "contratto Oracle"

`scripts/testcases.py` definisce ~55 casi che un'applicazione Oracle si
aspetta e che il proxy deve riprodurre identicamente:

- **sanity**: DUAL, USER, SYSDATE, SYS_GUID, hint `/*+ */`
- **funzioni**: NVL/NVL2/DECODE, TO_DATE/TO_CHAR, ADD_MONTHS, LISTAGG,
  stored function in SELECT, aritmetica date
- **tipi**: NUMBER, VARCHAR2/CHAR (padding), DATE vs TIMESTAMP, RAW, CLOB,
  BLOB, INTERVAL, stringa vuota = NULL, coercizioni implicite
- **sequenze**: `.NEXTVAL`/`.CURRVAL`, DEFAULT column
- **query**: ROWNUM, paginazione classica, outer join `(+)`, MINUS,
  CONNECT BY, ROLLUP, funzioni analitiche, sinonimi, FETCH FIRST
- **dml**: bind variabili, MERGE, `RETURNING INTO`, ROLLBACK/SAVEPOINT
- **plsql**: blocchi anonimi con bind OUT, package con stato di sessione,
  REF CURSOR, EXCEPTION/SQLERRM/SQLCODE, DBMS_OUTPUT, trigger
- **errori**: codici ORA-00001/01400/00942/00904/01722/01476/00900
  (il proxy deve restituire gli stessi codici ORA)

Le attese `expect_rows` sono deterministiche (nessun SYSDATE grezzo).

## Modalità

1. **oracle** — esegue tutto su Oracle 26ai Free, salva `results/baseline_oracle.json`
   e `results/report_oracle.md`. Questa e' la verita' di riferimento.
2. **postgres** — diagnostica: traduce ogni query con **sqlglot**
   (Oracle→Postgres) o override manuale (`pg_sql`), esegue su PostgreSQL+orafce
   e confronta con la baseline. Il report mostra le traduzioni applicate e
   dove PostgreSQL diverge (es. `''` vs NULL, stato di package).
   Questa modalita' misura **quanto lavoro di traduzione dovra' fare il proxy**.
3. **proxy** — stesso protocollo di `oracle` ma puntando al proxy
   (localhost:1527): ogni test deve risultare `MATCH` rispetto alla baseline.

## Note ambiente (WSL)

- `/dev/shm` >= 2GB richiesto da Oracle: questo WSL ha 3.9G, ok
- immagini e volumi vivono nel filesystem WSL (ext4), non su /mnt/c
- PyPI di questo host filtra `python-oracledb`: installare da GitHub
  `pip install https://github.com/oracle/python-oracledb/archive/refs/tags/v26.0.0.tar.gz`
  NON funziona (manca il submodule ODPI): usare
  `git clone --recurse-submodules --depth 1 -b v26.0.0 https://github.com/oracle/python-oracledb && pip install ./python-oracledb`
