# OracleBridge

Proxy che si presenta alle applicazioni come **Oracle Database** (protocollo
proprietario SQL*Net/TNS + TTC) e traduce in tempo reale verso **PostgreSQL**.
L'applicazione usa il driver Oracle standard (python-oracledb thin, e per
estensione qualsiasi client OCI che parli lo stesso dialetto TTC) senza
accorgere della differenza.

## Architettura

```
app Oracle ──TNS/TTC──▶ OracleBridge proxy ──SQL tradotto──▶ PostgreSQL
 (driver Oracle)        oraclebridge/                        (con orafce)
```

Componenti (`oraclebridge/`):

| Modulo | Ruolo |
|---|---|
| `tns.py` | Framing pacchetti SQL*Net (header 16/32 bit, CONNECT/ACCEPT, marker, DATA) |
| `buffer.py` | Primitive TTC (interi variabili con segno, stringhe length-prefixed, chunking 254) |
| `types.py` | Encoder/decoder tipi Oracle: NUMBER canonico, DATE 7 byte, TIMESTAMP, INTERVAL DS, RAW |
| `auth.py` | O5LOGON verifier 11g: sha1(password+salt) → AES-192, chiave sessione, PBKDF2-SHA512 combo key |
| `translate.py` | Motore Oracle→PostgreSQL: pre-regole ((+), ROWNUM, DUAL, sequenze, DBMS_LOB, RAWTOHEX), sqlglot, post-regole; PL/SQL semplificato |
| `pg.py` | Sessione PostgreSQL per client (transazione Oracle-like, metadata colonne, mapping OID→tipi ORA) |
| `ttc.py` | Macchina a stati TTC: auth (118/115), execute (94), fetch (5), commit/rollback, risposta describe/rows/io-vector/errori |
| `server.py` | Server TCP asyncio |

Scelte di protocollo verificate sui sorgenti python-oracledb thin
(`src/oracledb/impl/thin/*.pyx`, v26) e sul campo contro Oracle 26ai Free:

- il server negoza **field version 6** (11.2): formati campo piu' semplici,
  niente token/niente fast-auth/niente end-of-response → ogni risposta si
  chiude con messaggio ERROR o STATUS;
- il **rowcount DML** e il **cursor id** viaggiano nel messaggio ERROR(4) con
  numero 0; la fine delle righe e' ERROR 1403 (assorbito dal client);
- l'autenticazione richiede la password attesa in configurazione (l'O5LOGON
  11g la usa gia' nella fase 1); le credenziali decifrate aprono la sessione
  PostgreSQL (utente minuscolo).

## Uso

```bash
# backend PostgreSQL di test (vedi test/)
cd test && docker compose -f docker/docker-compose.yml up -d

# proxy
OB_LISTEN_PORT=1527 OB_PG_PORT=5433 OB_KNOWN_PASSWORD=TestApp_26ai \
  python3 -m oraclebridge
```

L'applicazione si connette a `localhost:1527/FREEPDB1` con
`testapp/TestApp_26ai` usando il driver Oracle standard.

## Stato (smoke test, 75 casi)

- baseline Oracle 26ai: **75/75 PASS** (`test/`, modalita' `oracle`)
- tramite proxy: **62/75 PASS**, confronto automatico vs baseline

Gap noti (documentati, non regressioni):

1. **PL/SQL avanzato** (pls.010-013, 008): DECLARE/FOR LOOP/cursori
   espliciti/BULK COLLECT/DBMS_OUTPUT.CHARARR richiedono un motore PL/SQL:
   il proxy supporta blocchi con chiamate, assegnamenti `:bind := expr`,
   `raise_application_error` e handler `WHEN OTHERS` con SQLCODE/SQLERRM.
2. **Semantica Oracle non replicabile a livello SQL**: `''` = NULL,
   `NEXTVAL` valutato una volta per riga, padding CHAR in `LENGTH`,
   aritmetica `TRUNC(date)` che in PG produce interval.
3. **CONNECT BY** non ancora tradotto (serve generazione recursive CTE).
4. dml.006/007 nel run completo: interazione piggyback CLOSE_CURSORS
   (statement cache piena) da perfezionare.
5. COLONNE LOB servite come VARCHAR2/RAW (max 32 KB) invece di locator LOB.

## Sviluppo del proxy: linguaggio scelto = Python

`python-oracledb` thin mode e' un'implementazione pura-Python del protocollo
client: e' servita come specifica eseguibile per scrivere il lato server
(nessuna documentazione Oracle pubblica esiste). `sqlglot` copre la
traduzione SQL, `psycopg` il backend. Per il throughput in produzione si puo'
portare il livello TNS/TTC in Go o Rust mantenendo i test come contratto.
