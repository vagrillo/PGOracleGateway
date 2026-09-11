"""Manifest dei smoke test OracleBridge.

Ogni test case e' un elemento del "contratto Oracle": cio' che un'applicazione
Oracle si aspetta dal driver/protocollo e che il proxy dovra' restituire
identicamente quando il backend e' PostgreSQL.

Modalita' di esecuzione (smoke_test.py):
- oracle   : esecuzione nativa su Oracle 26ai Free -> baseline
- proxy    : esecuzione tramite OracleBridge proxy -> deve matchare la baseline
- postgres : diagnostica: applica la traduzione (sqlglot / override pg_sql)
             e misura quanto PostgreSQL + orafce si avvicina al contratto.

Normalizzazione valori (vedere smoke_test.py): None, Decimal->str, date->ISO,
BLOB->hex, nomi colonna case-insensitive.
"""
from dataclasses import dataclass, field
from datetime import datetime

D = datetime  # alias


@dataclass
class Step:
    sql: str = None                      # SQL o blocco PL/SQL (oracle mode)
    binds: dict = field(default_factory=dict)
    out_binds: list = field(default_factory=list)   # nomi bind OUT (PL/SQL)
    expect_rows: list = None             # righe attese (deterministiche)
    expect_rowcount: int = None          # per DML
    expect_error: str = None             # es "ORA-00001"
    expect_out: dict = None              # attesi sui bind OUT {nome: valore}


@dataclass
class TC:
    id: str
    cat: str
    title: str
    steps: list = field(default_factory=list)
    pg_sql: str = None                   # override SQL PG (altrimenti sqlglot)
    pg_binds: dict = None
    pg_skip: str = None                  # motivo per cui PG non puo' replicare
    oracle_only: bool = False            # privo di senso in PG

    @staticmethod
    def q(id, cat, title, sql, binds=None, expect_rows=None,
          expect_rowcount=None, expect_error=None, **kw):
        return TC(id, cat, title,
                  steps=[Step(sql=sql, binds=dict(binds or {}),
                              expect_rows=expect_rows,
                              expect_rowcount=expect_rowcount,
                              expect_error=expect_error)],
                  **kw)

    @staticmethod
    def script(id, cat, title, steps, **kw):
        return TC(id, cat, title, steps=list(steps), **kw)


# mappa attesi SQLSTATE PostgreSQL per gli errori Oracle
PG_SQLSTATE = {
    "ORA-00001": "23505", "ORA-01400": "23502", "ORA-00942": "42P01",
    "ORA-00904": "42703", "ORA-01722": "22P02", "ORA-01476": "22012",
    "ORA-00900": "42601",
}

TESTS = [
    # ===================== SANITY / DUAL =====================
    TC.q("san.001", "sanity", "SELECT costante FROM DUAL",
         "SELECT 1 FROM dual", expect_rows=[(1,)]),
    TC.q("san.002", "sanity", "Stringa da DUAL",
         "SELECT 'Hello Bridge' FROM dual", expect_rows=[("Hello Bridge",)]),
    TC.q("san.003", "sanity", "Espressioni multiple",
         "SELECT 1+1, 'x' FROM dual", expect_rows=[(2, "x")]),
    TC.q("san.004", "sanity", "USER",
         "SELECT user FROM dual", expect_rows=[("TESTAPP",)],
         pg_sql="SELECT UPPER(user)"),
    TC.q("san.005", "sanity", "NULL letterale",
         "SELECT NULL FROM dual", expect_rows=[(None,)]),
    TC.q("san.006", "sanity", "SYSDATE coerente con CURRENT_DATE",
         "SELECT CASE WHEN TRUNC(sysdate) = TRUNC(CURRENT_DATE) THEN 'ok' ELSE 'ko' END FROM dual",
         expect_rows=[("ok",)],
         pg_sql="SELECT CASE WHEN date_trunc('day', now())::date = CURRENT_DATE THEN 'ok' ELSE 'ko' END"),
    TC.q("san.007", "sanity", "SYS_GUID() formato fisso",
         "SELECT LENGTH(rawtohex(sys_guid())) FROM dual", expect_rows=[(32,)],
         pg_sql="SELECT LENGTH(sys_guid()) * 2"),
    TC.q("san.008", "sanity", "Aritmetica con NULL",
         "SELECT 1 + NULL FROM dual", expect_rows=[(None,)]),
    TC.q("san.009", "sanity", "CAST NUMBER<->VARCHAR2",
         "SELECT CAST(42 AS VARCHAR2(10)), CAST('17' AS NUMBER) + 1 FROM dual",
         expect_rows=[("42", 18)]),
    TC.q("san.010", "sanity", "Hint Oracle tollerato",
         "SELECT /*+ FULL(emp) */ COUNT(*) FROM emp", expect_rows=[(14,)],
         pg_sql="SELECT COUNT(*) FROM emp"),

    # ===================== FUNZIONI =====================
    TC.q("fun.001", "funzioni", "NVL",
         "SELECT NVL(NULL, 'x'), NVL('a', 'x') FROM dual",
         expect_rows=[("x", "a")]),
    TC.q("fun.002", "funzioni", "NVL2",
         "SELECT NVL2(NULL, 1, 2), NVL2('a', 1, 2) FROM dual",
         expect_rows=[(2, 1)]),
    TC.q("fun.003", "funzioni", "DECODE",
         "SELECT DECODE(2, 1, 'uno', 2, 'due', 'altro') FROM dual",
         expect_rows=[("due",)]),
    TC.q("fun.004", "funzioni", "COALESCE",
         "SELECT COALESCE(NULL, NULL, 3) FROM dual", expect_rows=[(3,)]),
    TC.q("fun.005", "funzioni", "TO_DATE / TO_CHAR",
         "SELECT TO_CHAR(TO_DATE('2026-09-11','YYYY-MM-DD'),'DD/MM/YYYY') FROM dual",
         expect_rows=[("11/09/2026",)]),
    TC.q("fun.006", "funzioni", "ADD_MONTHS fine mese",
         "SELECT TO_CHAR(ADD_MONTHS(DATE '2026-01-31', 1), 'YYYY-MM-DD') FROM dual",
         expect_rows=[("2026-02-28",)]),
    TC.q("fun.007", "funzioni", "MONTHS_BETWEEN",
         "SELECT MONTHS_BETWEEN(DATE '2026-03-01', DATE '2026-01-01') FROM dual",
         expect_rows=[(2,)]),
    TC.q("fun.008", "funzioni", "LAST_DAY",
         "SELECT TO_CHAR(LAST_DAY(DATE '2026-02-10'), 'YYYY-MM-DD') FROM dual",
         expect_rows=[("2026-02-28",)]),
    TC.q("fun.009", "funzioni", "TRUNC su NUMBER",
         "SELECT TRUNC(15.789, 2), TRUNC(-15.789, 2) FROM dual",
         expect_rows=[(15.78, -15.78)]),
    TC.q("fun.010", "funzioni", "ROUND half-up",
         "SELECT ROUND(2.5), ROUND(-2.5), ROUND(15.789, 2) FROM dual",
         expect_rows=[(3, -3, 15.79)]),
    TC.q("fun.011", "funzioni", "INSTR / SUBSTR / LPAD",
         "SELECT INSTR('Oracle Bridge','Bridge'), SUBSTR('Oracle Bridge',8,6), LPAD('x',4,'-') FROM dual",
         expect_rows=[(8, "Bridge", "---x")]),
    TC.q("fun.012", "funzioni", "Aritmetica date",
         "SELECT TRUNC(sysdate + 1) - TRUNC(sysdate) FROM dual", expect_rows=[(1,)],
         pg_sql="SELECT (CURRENT_DATE + 1) - CURRENT_DATE"),
    TC.q("fun.013", "funzioni", "EXTRACT parti data",
         "SELECT EXTRACT(YEAR FROM DATE '2026-09-11'), EXTRACT(MONTH FROM DATE '2026-09-11') FROM dual",
         expect_rows=[(2026, 9)]),
    TC.q("fun.014", "funzioni", "LISTAGG",
         "SELECT LISTAGG(dname, ', ') WITHIN GROUP (ORDER BY dname) FROM dept",
         expect_rows=[("ACCOUNTING, OPERATIONS, RESEARCH, SALES",)],
         pg_sql="SELECT STRING_AGG(dname, ', ' ORDER BY dname) FROM dept"),
    TC.q("fun.015", "funzioni", "Stored function in SELECT",
         "SELECT f_sal_level(3200), f_sal_level(2000), f_sal_level(500) FROM dual",
         expect_rows=[("HIGH", "MID", "LOW")]),
    TC.q("fun.016", "funzioni", "MOD / ABS / CEIL / FLOOR",
         "SELECT MOD(10,3), ABS(-4), CEIL(1.2), FLOOR(1.8) FROM dual",
         expect_rows=[(1, 4, 2, 1)]),
    TC.q("fun.017", "funzioni", "GREATEST / LEAST",
         "SELECT GREATEST(3, 7, 5), LEAST(3, 7, 5) FROM dual",
         expect_rows=[(7, 3)]),
    TC.q("fun.018", "funzioni", "NVL su aggregato",
         "SELECT NVL(SUM(comm), 0) FROM emp WHERE deptno = 20",
         expect_rows=[(0,)]),

    # ===================== TIPI =====================
    TC.q("typ.001", "tipi", "NUMBER precisioni",
         "SELECT n_small, n_full, n_dec FROM t_types WHERE n_small = 127",
         expect_rows=[(127, 1234567890123, 123.45)]),
    TC.q("typ.002", "tipi", "VARCHAR2 / CHAR padding",
         "SELECT v_var, LENGTH(c_fixed), TRIM(c_fixed) FROM t_types WHERE v_var = 'ciao'",
         expect_rows=[("ciao", 5, "AB")],
         pg_sql="SELECT v_var, length(rpad(c_fixed::text, 5)), btrim(c_fixed) FROM t_types WHERE v_var = 'ciao'"),
    TC.q("typ.003", "tipi", "DATE e TIMESTAMP",
         "SELECT d_date, ts FROM t_types WHERE n_small = 127",
         expect_rows=[(D(2026, 9, 11), D(2026, 9, 11, 10, 20, 30, 123456))]),
    TC.q("typ.004", "tipi", "RAW hex",
         "SELECT rawtohex(raw16) FROM t_types WHERE n_small = 127",
         expect_rows=[("DEADBEEF01020304",)],
         pg_sql="SELECT UPPER(encode(raw16, 'hex')) FROM t_types WHERE n_small = 127"),
    TC.q("typ.005", "tipi", "CLOB",
         "SELECT DBMS_LOB.SUBSTR(big_text, 10, 1), LENGTH(big_text) FROM t_types WHERE n_small = 127",
         expect_rows=[("xyyyyyyyyy", 100)],
         pg_sql="SELECT substring(big_text, 1, 10), length(big_text) FROM t_types WHERE n_small = 127"),
    TC.q("typ.006", "tipi", "BLOB roundtrip",
         "SELECT rawtohex(dbms_lob.substr(big_bin, 3, 1)) FROM t_types WHERE n_small = 127",
         expect_rows=[("CAFE00",)],
         pg_sql="SELECT UPPER(encode(substring(big_bin, 1, 3), 'hex')) FROM t_types WHERE n_small = 127"),
    TC.q("typ.007", "tipi", "INTERVAL DAY TO SECOND",
         "SELECT i_day FROM t_types WHERE n_small = 127",
         expect_rows=[("1 02:03:04.567",)]),
    TC.q("typ.008", "tipi", "Stringa vuota = NULL",
         "SELECT ename, notes FROM emp WHERE empno = 8001",
         expect_rows=[("EMPTYTEST", None)],
         pg_skip="Oracle: '' e' NULL; PostgreSQL distingue '' da NULL"),
    TC.q("typ.009", "tipi", "Coercizione implicita stringa->numero",
         "SELECT ename FROM emp WHERE deptno = '20' ORDER BY empno",
         expect_rows=[("SMITH",), ("JONES",), ("SCOTT",), ("FORD",), ("EMPTYTEST",)]),

    # ===================== SEQUENZE =====================
    TC.q("seq.001", "sequenze", "NEXTVAL valutato una volta per riga",
         "SELECT seq_emp.NEXTVAL - seq_emp.NEXTVAL FROM dual",
         expect_rows=[(0,)],
         pg_skip="pseudo-colonna .NEXTVAL da riscrivere; PG nextval() avanza a ogni chiamata"),
    TC.q("seq.002", "sequenze", "DEFAULT column con sequence",
         "SELECT id, tag FROM t_default_seq ORDER BY id",
         expect_rows=[(1, "primo"), (2, "secondo")]),

    # ===================== QUERY ORACLE-SPECIFIC =====================
    TC.q("ora.001", "query", "ROWNUM limit (subquery ordinata)",
         "SELECT ename FROM (SELECT ename FROM emp ORDER BY ename) WHERE ROWNUM <= 3",
         expect_rows=[("ALLEN",), ("BLAKE",), ("CLARK",)],
         pg_sql="SELECT ename FROM emp ORDER BY ename LIMIT 3"),
    TC.q("ora.002", "query", "Paginazione ROWNUM subquery",
         "SELECT ename FROM (SELECT ename, ROWNUM rnum FROM emp ORDER BY ename) WHERE rnum BETWEEN 2 AND 3",
         expect_rows=[("BLAKE",), ("CLARK",)],
         pg_sql="SELECT ename FROM (SELECT ename, ROW_NUMBER() OVER (ORDER BY ename) AS rnum FROM emp) x WHERE rnum BETWEEN 2 AND 3"),
    TC.q("ora.003", "query", "Outer join (+)",
         "SELECT d.dname, COUNT(e.empno) FROM dept d, emp e WHERE e.deptno(+) = d.deptno GROUP BY d.dname ORDER BY d.dname",
         expect_rows=[("ACCOUNTING", 3), ("OPERATIONS", 0), ("RESEARCH", 5), ("SALES", 6)],
         pg_sql="SELECT d.dname, COUNT(e.empno) FROM dept d LEFT JOIN emp e ON e.deptno = d.deptno GROUP BY d.dname ORDER BY d.dname"),
    TC.q("ora.004", "query", "MINUS",
         "SELECT deptno FROM dept MINUS SELECT deptno FROM emp ORDER BY deptno",
         expect_rows=[(40,)]),
    TC.q("ora.005", "query", "CONNECT BY gerarchico",
         "SELECT LEVEL, ename FROM emp START WITH mgr IS NULL CONNECT BY PRIOR empno = mgr AND LEVEL <= 2 ORDER BY LEVEL, ename",
         expect_rows=[(1, "KING"), (2, "BLAKE"), (2, "CLARK"), (2, "JONES")],
         pg_sql="WITH RECURSIVE t(lev, ename, empno) AS ("
                "SELECT 1, ename, empno FROM emp WHERE mgr IS NULL "
                "UNION ALL SELECT t.lev+1, e.ename, e.empno FROM emp e "
                "JOIN t ON e.mgr = t.empno WHERE t.lev < 2) "
                "SELECT lev, ename FROM t ORDER BY lev, ename"),
    TC.q("ora.006", "query", "RANK() OVER",
         "SELECT ename, sal FROM (SELECT ename, sal, RANK() OVER (ORDER BY sal DESC) rk FROM emp) WHERE rk = 1",
         expect_rows=[("KING", 5000)]),
    TC.q("ora.007", "query", "GROUP BY ROLLUP",
         "SELECT deptno, COUNT(*) FROM emp GROUP BY ROLLUP(deptno) ORDER BY deptno NULLS LAST",
         expect_rows=[(10, 3), (20, 5), (30, 6), (None, 14)]),
    TC.q("ora.008", "query", "Sinonimo trasparente",
         "SELECT COUNT(*) FROM e", expect_rows=[(14,)],
         pg_skip="PostgreSQL non ha sinonimi"),
    TC.q("ora.009", "query", "FETCH FIRST + ORDER BY alias/posizione",
         "SELECT ename, sal AS retribuzione FROM emp ORDER BY retribuzione DESC, 1 FETCH FIRST 2 ROWS ONLY",
         expect_rows=[("KING", 5000), ("FORD", 3000)]),
    TC.q("ora.010", "query", "UNION deduplica",
         "SELECT job FROM emp WHERE deptno = 10 UNION SELECT job FROM emp WHERE deptno = 10 ORDER BY job",
         expect_rows=[("CLERK",), ("MANAGER",), ("PRESIDENT",)]),

    # ===================== DML / TRANSAZIONI =====================
    TC.q("dml.001", "dml", "INSERT rowcount",
         "INSERT INTO t_log(msg) VALUES ('smoke dml.001')", expect_rowcount=1),
    TC.q("dml.002", "dml", "UPDATE con bind",
         "UPDATE emp SET comm = :c WHERE empno = :e", binds={"c": 77, "e": 7369},
         expect_rowcount=1),
    TC.q("dml.003", "dml", "DELETE rowcount 0",
         "DELETE FROM emp WHERE empno = 99999", expect_rowcount=0),
    TC.q("dml.004", "dml", "MERGE update ramo MATCHED",
         "MERGE INTO t_default_seq d USING (SELECT 1 AS id, 'terzo' AS tag FROM dual) s "
         "ON (d.id = s.id) WHEN MATCHED THEN UPDATE SET d.tag = s.tag "
         "WHEN NOT MATCHED THEN INSERT (tag) VALUES (s.tag)",
         expect_rowcount=1,
         pg_sql="MERGE INTO t_default_seq d USING (SELECT 1 AS id, 'terzo' AS tag) s "
                "ON (d.id = s.id) WHEN MATCHED THEN UPDATE SET tag = s.tag "
                "WHEN NOT MATCHED THEN INSERT (tag) VALUES (s.tag)"),
    TC.script("dml.005", "dml", "INSERT RETURNING INTO bind OUT", [
        Step(sql="INSERT INTO t_default_seq(tag) VALUES ('ritorno') "
                 "RETURNING id INTO :newid",
             out_binds=["newid"]),
    ], pg_sql="INSERT INTO t_default_seq(tag) VALUES ('ritorno') RETURNING id"),
    TC.script("dml.006", "dml", "ROLLBACK annulla", [
        Step(sql="INSERT INTO t_log(msg) VALUES ('da rollbackare')"),
        Step(sql="ROLLBACK"),
        Step(sql="SELECT COUNT(*) FROM t_log WHERE msg = 'da rollbackare'",
             expect_rows=[(0,)]),
    ]),
    TC.script("dml.007", "dml", "SAVEPOINT parziale", [
        Step(sql="INSERT INTO t_log(msg) VALUES ('keep')"),
        Step(sql="SAVEPOINT sp1"),
        Step(sql="INSERT INTO t_log(msg) VALUES ('drop')"),
        Step(sql="ROLLBACK TO sp1"),
        Step(sql="SELECT COUNT(*) FROM t_log WHERE msg IN ('keep','drop')",
             expect_rows=[(1,)]),
        Step(sql="ROLLBACK"),
    ]),

    # ===================== PL/SQL =====================
    TC.q("pls.010", "plsql", "Blocco anonimo FOR loop con bind OUT",
         None,  # sorgente assegnato sotto da PLSQL_SRC
         pg_skip="blocco anonimo PL/SQL -> DO block PL/pgSQL"),
    TC.q("pls.011", "plsql", "EXCEPTION WHEN OTHERS + SQLERRM",
         None, pg_skip="exception handler nel blocco"),
    TC.q("pls.012", "plsql", "Cursore esplicito e %TYPE",
         None, pg_skip="attributi %TYPE / cursori espliciti"),
    TC.q("pls.013", "plsql", "BULK COLLECT",
         None, pg_skip="BULK COLLECT oracle-only"),
    TC.q("pls.002", "plsql", "Package: stato di sessione",
         None, pg_skip="stato di package non esiste in PostgreSQL"),
    TC.q("pls.003", "plsql", "Funzione package con SELECT INTO",
         "SELECT pkg_demo.get_emp_name(7839) FROM dual",
         expect_rows=[("KING",)],
         pg_sql="SELECT pkg_demo.get_emp_name(7839)"),
    TC.q("pls.004", "plsql", "NO_DATA_FOUND -> NULL",
         "SELECT pkg_demo.get_emp_name(1) FROM dual",
         expect_rows=[(None,)],
         pg_sql="SELECT pkg_demo.get_emp_name(1)"),
    TC.q("pls.005", "plsql", "REF CURSOR via package",
         None, pg_skip="REF CURSOR -> funzione setof/cursore server-side"),
    TC.q("pls.006", "plsql", "SQLCODE dentro EXCEPTION",
         None, pg_skip="blocco con exception"),
    TC.q("pls.007", "plsql", "RAISE_APPLICATION_ERROR",
         "BEGIN raise_application_error(-20001, 'boom bizantino'); END;",
         expect_error="ORA-20001", oracle_only=True),
    TC.q("pls.008", "plsql", "DBMS_OUTPUT",
         None, pg_skip="instradamento dbms_output"),
    TC.script("pls.009", "plsql", "Trigger EMP genera audit", [
        Step(sql="DELETE FROM t_audit"),
        Step(sql="INSERT INTO emp (empno, ename, job, hiredate, sal, deptno) "
                 "VALUES (8100, 'TRGTEST', 'CLERK', SYSDATE, 1000, 30)"),
        Step(sql="SELECT COUNT(*) FROM t_audit WHERE action = 'INSERT'",
             expect_rows=[(1,)]),
        Step(sql="DELETE FROM emp WHERE empno = 8100"),
    ]),

    # ===================== ERRORI =====================
    TC.q("err.001", "errori", "Unique violation",
         "INSERT INTO dept VALUES (10, 'DUP', 'X')", expect_error="ORA-00001"),
    TC.q("err.002", "errori", "NOT NULL violation",
         "INSERT INTO dept(deptno) VALUES (99)", expect_error="ORA-01400"),
    TC.q("err.003", "errori", "Tabella inesistente",
         "SELECT * FROM tabella_che_non_esiste", expect_error="ORA-00942"),
    TC.q("err.004", "errori", "Colonna inesistente",
         "SELECT colonna_inesistente FROM dept", expect_error="ORA-00904"),
    TC.q("err.005", "errori", "Numero non valido",
         "SELECT TO_NUMBER('abc') FROM dual", expect_error="ORA-01722"),
    TC.q("err.006", "errori", "Divisione per zero",
         "SELECT 1/0 FROM dual", expect_error="ORA-01476"),
    TC.q("err.007", "errori", "Statement non riconosciuto",
         "FLIPPAROLA TOTALE", expect_error="ORA-00900"),
]

# ------------------------------------------------------------------
# Sorgenti PL/SQL veri (oracle mode) per i test pls.*
# ------------------------------------------------------------------
PLSQL_SRC = {
    "pls.010": ("DECLARE l_tot NUMBER := 0; "
                "BEGIN FOR r IN (SELECT sal FROM emp WHERE deptno = 20) LOOP "
                "l_tot := l_tot + r.sal; END LOOP; :out := l_tot; END;",
                {"out": None}, ["out"], {"out": 10675}),
    "pls.011": ("DECLARE l_msg VARCHAR2(200); "
                "BEGIN SELECT ename INTO l_msg FROM emp WHERE empno = 999; "
                ":out := l_msg; EXCEPTION WHEN NO_DATA_FOUND THEN "
                ":out := 'caught:'||SQLERRM; END;",
                {"out": None}, ["out"],
                {"out": "caught:ORA-01403: no data found"}),
    "pls.012": ("DECLARE l_name emp.ename%TYPE; CURSOR c IS SELECT ename FROM emp "
                "WHERE empno = 7698; BEGIN OPEN c; FETCH c INTO l_name; CLOSE c; "
                ":out := l_name; END;",
                {"out": None}, ["out"], {"out": "BLAKE"}),
    "pls.013": ("DECLARE TYPE t_tab IS TABLE OF emp.sal%TYPE; l_sals t_tab; "
                "BEGIN SELECT sal BULK COLLECT INTO l_sals FROM emp "
                "WHERE deptno = 10; :out := l_sals.COUNT; END;",
                {"out": None}, ["out"], {"out": 3}),
    "pls.002": ("BEGIN pkg_demo.set_x(5); :out := pkg_demo.get_x; END;",
                {"out": None}, ["out"], {"out": 5}),
    "pls.006": ("BEGIN RAISE_APPLICATION_ERROR(-20001,'boom'); EXCEPTION "
                "WHEN OTHERS THEN :out := SQLCODE; END;",
                {"out": None}, ["out"], {"out": -20001}),
    "pls.005": ("BEGIN pkg_demo.open_emps(10, :cur); END;",
                {"cur": None}, ["cur"],
                {"cur": [(7782, "CLARK", 2450), (7839, "KING", 5000),
                         (7934, "MILLER", 1300)]}),
    "pls.008": ("DECLARE l_lines DBMS_OUTPUT.CHARARR; l_num INTEGER := 10; "
                "BEGIN DBMS_OUTPUT.ENABLE(1000000); "
                "DBMS_OUTPUT.PUT_LINE('ciao bridge'); "
                "DBMS_OUTPUT.PUT_LINE('seconda riga'); "
                "DBMS_OUTPUT.GET_LINES(l_lines, l_num); "
                ":l1 := l_lines(1); :l2 := l_lines(2); END;",
                {"l1": None, "l2": None}, ["l1", "l2"],
                {"l1": "ciao bridge", "l2": "seconda riga"}),
}
for t in TESTS:
    if t.id in PLSQL_SRC:
        src, binds, outs, expect = PLSQL_SRC[t.id]
        t.steps[0].sql = src
        t.steps[0].binds = binds
        t.steps[0].out_binds = outs
        t.steps[0].expect_out = expect

CATEGORIES = ["sanity", "funzioni", "tipi", "sequenze", "query", "dml",
              "plsql", "errori"]
