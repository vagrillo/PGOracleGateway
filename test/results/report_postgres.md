# Smoke test OracleBridge — mode: postgres
Generato: 2026-09-11T15:19:10
Database: PostgreSQL 17.11 (Debian 17.11-1.pgdg13+2) on x86_64-pc-linux-gnu, compiled by gcc (Debian 14.2.0-19) 14.2.0, 64-bit

## Traduzioni applicate (sqlglot / override)

- `san.001` (sqlglot): `SELECT 1 FROM dual`
- `san.002` (sqlglot): `SELECT 'Hello Bridge' FROM dual`
- `san.003` (sqlglot): `SELECT 1 + 1, 'x' FROM dual`
- `san.004` (override): `SELECT UPPER(user)`
- `san.005` (sqlglot): `SELECT NULL FROM dual`
- `san.006` (override): `SELECT CASE WHEN date_trunc('day', now())::date = CURRENT_DATE THEN 'ok' ELSE 'ko' END`
- `san.007` (override): `SELECT LENGTH(sys_guid()) * 2`
- `san.008` (sqlglot): `SELECT 1 + NULL FROM dual`
- `san.009` (sqlglot): `SELECT CAST(42 AS VARCHAR(10)), CAST('17' AS DECIMAL) + 1 FROM dual`
- `san.010` (override): `SELECT COUNT(*) FROM emp`
- `fun.001` (sqlglot): `SELECT COALESCE(NULL, 'x'), COALESCE('a', 'x') FROM dual`
- `fun.002` (sqlglot): `SELECT CASE WHEN NOT NULL IS NULL THEN 1 ELSE 2 END, CASE WHEN NOT 'a' IS NULL THEN 1 ELSE 2 END FROM dual`
- `fun.003` (sqlglot): `SELECT CASE WHEN 2 = 1 THEN 'uno' WHEN 2 = 2 THEN 'due' ELSE 'altro' END FROM dual`
- `fun.004` (sqlglot): `SELECT COALESCE(NULL, NULL, 3) FROM dual`
- `fun.005` (sqlglot): `SELECT TO_CHAR(TO_DATE('2026-09-11', 'YYYY-MM-DD'), 'DD/MM/YYYY') FROM dual`
- `fun.006` (sqlglot): `SELECT TO_CHAR(ADD_MONTHS(CAST('2026-01-31' AS DATE), 1), 'YYYY-MM-DD') FROM dual`
- `fun.007` (sqlglot): `SELECT MONTHS_BETWEEN(CAST('2026-03-01' AS DATE), CAST('2026-01-01' AS DATE)) FROM dual`
- `fun.008` (sqlglot): `SELECT TO_CHAR(CAST(DATE_TRUNC('MONTH', CAST('2026-02-10' AS DATE)) + INTERVAL '1 MONTH' - INTERVAL '1 DAY' AS DATE), 'YYYY-MM-DD') FROM dual`
- `fun.009` (sqlglot): `SELECT TRUNC(15.789, 2), TRUNC(-15.789, 2) FROM dual`
- `fun.010` (sqlglot): `SELECT ROUND(2.5), ROUND(-2.5), ROUND(CAST(15.789 AS DECIMAL), 2) FROM dual`
- `fun.011` (sqlglot): `SELECT POSITION('Bridge' IN 'Oracle Bridge'), SUBSTRING('Oracle Bridge' FROM 8 FOR 6), LPAD('x', 4, '-') FROM dual`
- `fun.012` (override): `SELECT (CURRENT_DATE + 1) - CURRENT_DATE`
- `fun.013` (sqlglot): `SELECT EXTRACT(YEAR FROM CAST('2026-09-11' AS DATE)), EXTRACT(MONTH FROM CAST('2026-09-11' AS DATE)) FROM dual`
- `fun.014` (override): `SELECT STRING_AGG(dname, ', ' ORDER BY dname) FROM dept`
- `fun.015` (sqlglot): `SELECT F_SAL_LEVEL(3200), F_SAL_LEVEL(2000), F_SAL_LEVEL(500) FROM dual`
- `fun.016` (sqlglot): `SELECT 10 % 3, ABS(-4), CEIL(1.2), FLOOR(1.8) FROM dual`
- `fun.017` (sqlglot): `SELECT GREATEST(3, 7, 5), LEAST(3, 7, 5) FROM dual`
- `fun.018` (sqlglot): `SELECT COALESCE(SUM(comm), 0) FROM emp WHERE deptno = 20`
- `typ.001` (sqlglot): `SELECT n_small, n_full, n_dec FROM t_types WHERE n_small = 127`
- `typ.002` (override): `SELECT v_var, length(rpad(c_fixed::text, 5)), btrim(c_fixed) FROM t_types WHERE v_var = 'ciao'`
- `typ.003` (sqlglot): `SELECT d_date, ts FROM t_types WHERE n_small = 127`
- `typ.004` (override): `SELECT UPPER(encode(raw16, 'hex')) FROM t_types WHERE n_small = 127`
- `typ.005` (override): `SELECT substring(big_text, 1, 10), length(big_text) FROM t_types WHERE n_small = 127`
- `typ.006` (override): `SELECT UPPER(encode(substring(big_bin, 1, 3), 'hex')) FROM t_types WHERE n_small = 127`
- `typ.007` (sqlglot): `SELECT i_day FROM t_types WHERE n_small = 127`
- `typ.009` (sqlglot): `SELECT ename FROM emp WHERE deptno = '20' ORDER BY empno`
- `seq.002` (sqlglot): `SELECT id, tag FROM t_default_seq ORDER BY id`
- `ora.001` (override): `SELECT ename FROM emp ORDER BY ename LIMIT 3`
- `ora.002` (override): `SELECT ename FROM (SELECT ename, ROW_NUMBER() OVER (ORDER BY ename) AS rnum FROM emp) x WHERE rnum BETWEEN 2 AND 3`
- `ora.003` (override): `SELECT d.dname, COUNT(e.empno) FROM dept d LEFT JOIN emp e ON e.deptno = d.deptno GROUP BY d.dname ORDER BY d.dname`
- `ora.004` (sqlglot): `SELECT deptno FROM dept EXCEPT SELECT deptno FROM emp ORDER BY deptno`
- `ora.005` (override): `WITH RECURSIVE t(lev, ename, empno) AS (SELECT 1, ename, empno FROM emp WHERE mgr IS NULL UNION ALL SELECT t.lev+1, e.ename, e.empno FROM emp e JOIN t ON e.mgr = t.empno WHERE t.lev < 2) SELECT lev, ename FROM t ORDER BY lev, ename`
- `ora.006` (sqlglot): `SELECT ename, sal FROM (SELECT ename, sal, RANK() OVER (ORDER BY sal DESC) AS rk FROM emp) WHERE rk = 1`
- `ora.007` (sqlglot): `SELECT deptno, COUNT(*) FROM emp GROUP BY ROLLUP (deptno) ORDER BY deptno`
- `ora.009` (sqlglot): `SELECT ename, sal AS retribuzione FROM emp ORDER BY retribuzione DESC, 1 FETCH FIRST 2 ROWS ONLY`
- `ora.010` (sqlglot): `SELECT job FROM emp WHERE deptno = 10 UNION SELECT job FROM emp WHERE deptno = 10 ORDER BY job`
- `dml.001` (sqlglot): `INSERT INTO t_log (msg) VALUES ('smoke dml.001')`
- `dml.002` (sqlglot): `UPDATE emp SET comm = %(c)s WHERE empno = %(e)s`
- `dml.003` (sqlglot): `DELETE FROM emp WHERE empno = 99999`
- `dml.004` (override): `MERGE INTO t_default_seq d USING (SELECT 1 AS id, 'terzo' AS tag) s ON (d.id = s.id) WHEN MATCHED THEN UPDATE SET tag = s.tag WHEN NOT MATCHED THEN INSERT (tag) VALUES (s.tag)`
- `dml.005` (override): `INSERT INTO t_default_seq(tag) VALUES ('ritorno') RETURNING id`
- `dml.006` (sqlglot): `INSERT INTO t_log (msg) VALUES ('da rollbackare')`
- `dml.006` (sqlglot): `SELECT COUNT(*) FROM t_log WHERE msg = 'da rollbackare'`
- `dml.007` (sqlglot): `INSERT INTO t_log (msg) VALUES ('keep')`
- `dml.007` (sqlglot): `INSERT INTO t_log (msg) VALUES ('drop')`
- `dml.007` (sqlglot): `SELECT COUNT(*) FROM t_log WHERE msg IN ('keep', 'drop')`
- `pls.003` (override): `SELECT pkg_demo.get_emp_name(7839)`
- `pls.004` (override): `SELECT pkg_demo.get_emp_name(1)`
- `pls.009` (sqlglot): `DELETE FROM t_audit`
- `pls.009` (sqlglot): `INSERT INTO emp (empno, ename, job, hiredate, sal, deptno) VALUES (8100, 'TRGTEST', 'CLERK', CURRENT_TIMESTAMP, 1000, 30)`
- `pls.009` (sqlglot): `SELECT COUNT(*) FROM t_audit WHERE action = 'INSERT'`
- `pls.009` (sqlglot): `DELETE FROM emp WHERE empno = 8100`
- `err.001` (sqlglot): `INSERT INTO dept VALUES (10, 'DUP', 'X')`
- `err.002` (sqlglot): `INSERT INTO dept (deptno) VALUES (99)`
- `err.003` (sqlglot): `SELECT * FROM tabella_che_non_esiste`
- `err.004` (sqlglot): `SELECT colonna_inesistente FROM dept`
- `err.005` (sqlglot): `SELECT CAST('abc' AS DOUBLE PRECISION) FROM dual`
- `err.006` (sqlglot): `SELECT CAST(1 AS DOUBLE PRECISION) / 0 FROM dual`
- `err.007` (sqlglot): `FLIPPAROLA AS TOTALE`

## Riepilogo: PASS=63, SKIP=12
- **PASS**: 63
- **SKIP**: 12 -> typ.008, seq.001, ora.008, pls.010, pls.011, pls.012, pls.013, pls.002, pls.005, pls.006, pls.007, pls.008

| Test | Stato | Dettaglio |
|------|-------|-----------|
| san.001 | PASS |  vs oracle: MATCH |
| san.002 | PASS |  vs oracle: MATCH |
| san.003 | PASS |  vs oracle: MATCH |
| san.004 | PASS |  vs oracle: MATCH |
| san.005 | PASS |  vs oracle: MATCH |
| san.006 | PASS |  vs oracle: MATCH |
| san.007 | PASS |  vs oracle: MATCH |
| san.008 | PASS |  vs oracle: MATCH |
| san.009 | PASS |  vs oracle: MATCH |
| san.010 | PASS |  vs oracle: MATCH |
| fun.001 | PASS |  vs oracle: MATCH |
| fun.002 | PASS |  vs oracle: MATCH |
| fun.003 | PASS |  vs oracle: MATCH |
| fun.004 | PASS |  vs oracle: MATCH |
| fun.005 | PASS |  vs oracle: MATCH |
| fun.006 | PASS |  vs oracle: MATCH |
| fun.007 | PASS |  vs oracle: MATCH |
| fun.008 | PASS |  vs oracle: MATCH |
| fun.009 | PASS |  vs oracle: MATCH |
| fun.010 | PASS |  vs oracle: MATCH |
| fun.011 | PASS |  vs oracle: MATCH |
| fun.012 | PASS |  vs oracle: MATCH |
| fun.013 | PASS |  vs oracle: MATCH |
| fun.014 | PASS |  vs oracle: MATCH |
| fun.015 | PASS |  vs oracle: MATCH |
| fun.016 | PASS |  vs oracle: MATCH |
| fun.017 | PASS |  vs oracle: MATCH |
| fun.018 | PASS |  vs oracle: MATCH |
| typ.001 | PASS |  vs oracle: MATCH |
| typ.002 | PASS |  vs oracle: MATCH |
| typ.003 | PASS |  vs oracle: MATCH |
| typ.004 | PASS |  vs oracle: MATCH |
| typ.005 | PASS |  vs oracle: MATCH |
| typ.006 | PASS |  vs oracle: MATCH |
| typ.007 | PASS |  vs oracle: MATCH |
| typ.008 | SKIP | Oracle: '' e' NULL; PostgreSQL distingue '' da NULL |
| typ.009 | PASS |  vs oracle: MATCH |
| seq.001 | SKIP | pseudo-colonna .NEXTVAL da riscrivere; PG nextval() avanza a ogni chiamata |
| seq.002 | PASS |  vs oracle: MATCH |
| ora.001 | PASS |  vs oracle: MATCH |
| ora.002 | PASS |  vs oracle: MATCH |
| ora.003 | PASS |  vs oracle: MATCH |
| ora.004 | PASS |  vs oracle: MATCH |
| ora.005 | PASS |  vs oracle: MATCH |
| ora.006 | PASS |  vs oracle: MATCH |
| ora.007 | PASS |  vs oracle: MATCH |
| ora.008 | SKIP | PostgreSQL non ha sinonimi |
| ora.009 | PASS |  vs oracle: MATCH |
| ora.010 | PASS |  vs oracle: MATCH |
| dml.001 | PASS |  vs oracle: MATCH |
| dml.002 | PASS |  vs oracle: MATCH |
| dml.003 | PASS |  vs oracle: MATCH |
| dml.004 | PASS |  vs oracle: MATCH |
| dml.005 | PASS |  \| divergente da Oracle vs oracle: DIVERGENT |
| dml.006 | PASS |  vs oracle: MATCH |
| dml.007 | PASS |  vs oracle: MATCH |
| pls.010 | SKIP | blocco anonimo PL/SQL -> DO block PL/pgSQL |
| pls.011 | SKIP | exception handler nel blocco |
| pls.012 | SKIP | attributi %TYPE / cursori espliciti |
| pls.013 | SKIP | BULK COLLECT oracle-only |
| pls.002 | SKIP | stato di package non esiste in PostgreSQL |
| pls.003 | PASS |  vs oracle: MATCH |
| pls.004 | PASS |  vs oracle: MATCH |
| pls.005 | SKIP | REF CURSOR -> funzione setof/cursore server-side |
| pls.006 | SKIP | blocco con exception |
| pls.007 | SKIP | oracle-only |
| pls.008 | SKIP | instradamento dbms_output |
| pls.009 | PASS |  vs oracle: MATCH |
| err.001 | PASS |  vs oracle: MATCH |
| err.002 | PASS |  vs oracle: MATCH |
| err.003 | PASS |  vs oracle: MATCH |
| err.004 | PASS |  vs oracle: MATCH |
| err.005 | PASS |  vs oracle: MATCH |
| err.006 | PASS |  vs oracle: MATCH |
| err.007 | PASS |  vs oracle: MATCH |