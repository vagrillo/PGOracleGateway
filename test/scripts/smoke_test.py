#!/usr/bin/env python3
"""OracleBridge smoke test - runner.

Modes:
  oracle    native connection to Oracle 26ai Free; produces the baseline
            (results/baseline_oracle.json) and report (results/report_oracle.md)
  postgres  diagnostics: translates the queries (sqlglot or pg_sql override)
            and runs them on PostgreSQL+orafce; compares with the baseline
  proxy     uses the OracleBridge proxy as if it were Oracle; compares each
            result with the baseline: the proxy is ready when all MATCH

Usage:
  python3 smoke_test.py --mode oracle
  python3 smoke_test.py --mode postgres
  python3 smoke_test.py --mode proxy
  python3 smoke_test.py --mode oracle --filter ora.   # category/id only
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import oracledb
import sqlglot

sys.path.insert(0, str(Path(__file__).parent))
from config import ORACLE, POSTGRES, PROXY, RESULTS_DIR  # noqa: E402
from testcases import TESTS, PG_SQLSTATE  # noqa: E402

BASELINE = Path(RESULTS_DIR) / "baseline_oracle.json"


# ---------------------------------------------------------------------------
# Value normalization for stable JSON comparisons
# ---------------------------------------------------------------------------
def norm_value(v):
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [norm_value(x) for x in v]
    if isinstance(v, oracledb.Cursor):
        return norm_rows(v.fetchall())
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, Decimal):
        f = float(v)
        return round(f, 6)
    if isinstance(v, datetime):
        return v.isoformat(sep="T", timespec="microseconds").replace("+00:00", "Z")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, timedelta):
        total = abs(v.total_seconds())
        d = int(total // 86400)
        rem = total - d * 86400
        h = int(rem // 3600)
        rem -= h * 3600
        m = int(rem // 60)
        s = int(rem - m * 60)
        frac = f"{rem - int(rem):.6f}".split(".")[1][:3]
        sign = "-" if v.total_seconds() < 0 else ""
        return f"{sign}{d} {h:02}:{m:02}:{s:02}.{frac}"
    if isinstance(v, (bytes, bytearray, memoryview)):
        return "hex:" + bytes(v).hex().upper()
    if oracledb and isinstance(v, oracledb.LOB):
        return norm_value(v.read())
    return str(v)


def norm_rows(rows):
    return [[norm_value(v) for v in row] for row in rows]


def norm_out(outs):
    if outs is None:
        return None
    return {k: norm_value(v) for k, v in outs.items()}


# ---------------------------------------------------------------------------
# Esecuzione step (oracledb: Oracle nativo o proxy)
# ---------------------------------------------------------------------------
ORA_CODE_RE = re.compile(r"ORA-(\d{5})")


def ora_code(e) -> str:
    code = getattr(e, "full_code", None)
    if code and code.startswith("ORA-"):
        return code
    m = ORA_CODE_RE.search(str(e))
    return f"ORA-{m.group(1)}" if m else f"UNKNOWN:{type(e).__name__}"


class OraRunner:
    def __init__(self, conn, mode):
        self.conn = conn
        self.mode = mode
        oracledb.defaults.fetch_lobs = False

    def execute_step(self, step: "Step"):
        """Ritorna dict: {rows,rowcount,out,error,columns} normalizzati."""
        cur = self.conn.cursor()
        binds = dict(step.binds)
        out_vars = {}
        try:
            if step.out_binds:
                for name in step.out_binds:
                    exp = (step.expect_out or {}).get(name)
                    if exp and isinstance(exp, list):
                        var = cur.var(oracledb.DB_TYPE_CURSOR)
                    elif exp and isinstance(exp, str):
                        var = cur.var(str)
                    else:
                        var = cur.var(int)
                    out_vars[name] = var
                    binds[name] = var
                cur.execute(step.sql, binds)
                out = {}
                for name, var in out_vars.items():
                    out[name] = var.getvalue()  # normalizza norm_out
                result = {"out": norm_out(out)}
            else:
                cur.execute(step.sql, binds or None)
                result = {}
            if step.expect_error:
                # ci si aspettava un errore ma e' andata bene
                result["error"] = None
                result["rows"] = None
                if cur.description:
                    try:
                        result["rows"] = norm_rows(cur.fetchall())
                    except Exception:  # noqa: BLE001
                        pass
            elif cur.description:
                result["columns"] = [d[0].upper() for d in cur.description]
                result["rows"] = norm_rows(cur.fetchall())
                result["rowcount"] = len(result["rows"])
            else:
                result["rows"] = None
                result["rowcount"] = cur.rowcount
            return result
        except oracledb.DatabaseError as e:
            return {"error": ora_code(e), "rows": None, "rowcount": None,
                    "out": None, "message": str(e).split("\n")[0]}
        finally:
            cur.close()

    def run_dbms_output_test(self):
        # replaced by the pls.008 PL/SQL block in testcases.PLSQL_SRC
        return {"status": "SKIP", "detail": "replaced by pls.008 block"}

    def run_tests(self, tests):
        results = {}
        for tc in tests:
            steps_res = []
            self.conn.rollback()  # stato pulito a inizio test
            ok = True
            detail = ""
            for step in tc.steps:
                res = self.execute_step(step)
                steps_res.append(res)
                v = self.verify_step(step, res)
                if not v[0]:
                    ok, detail = False, v[1]
                    break
            self.conn.rollback()  # cleanup
            results[tc.id] = {"status": "PASS" if ok else "FAIL",
                              "detail": detail, "steps": steps_res}
        return results

    def verify_step(self, step, res):
        if step.expect_error:
            got = res.get("error")
            if got != step.expect_error:
                return False, f"expected error {step.expect_error}, got {got}"
            return True, ""
        if res.get("error"):
            return False, f"unexpected error {res['error']}: {res.get('message','')}"
        if step.expect_rows is not None:
            want = norm_rows(step.expect_rows)
            if res.get("rows") != want:
                return False, f"expected rows {want}, got {res.get('rows')}"
        if step.expect_rowcount is not None and res.get("rowcount") != step.expect_rowcount:
            return False, f"expected rowcount {step.expect_rowcount}, got {res.get('rowcount')}"
        if step.expect_out:
            for k, exp in step.expect_out.items():
                got = (res.get("out") or {}).get(k)
                if isinstance(exp, list):  # cursore
                    exp = norm_rows(exp)
                elif not isinstance(exp, str):
                    exp = norm_value(exp)
                if got != exp:
                    return False, f"OUT bind {k}: expected {exp}, got {got}"
        return True, ""


# ---------------------------------------------------------------------------
# PostgreSQL: translation + diagnostic execution
# ---------------------------------------------------------------------------
PLACEHOLDER_RE = re.compile(r"(?<!:):([A-Za-z_]\w*)")


def to_pg_sql(step, tc):
    """Ritorna (sql_pg, origine) con origine in {'override','sqlglot','raw'}."""
    if tc.pg_sql:
        return tc.pg_sql, "override"
    sql = step.sql
    if sql is None:
        return None, "n/a"
    if re.match(r"^\s*(BEGIN|DECLARE)\b", sql, re.I) and ";" in sql:
        return None, "PL/SQL"
    if re.match(r"^\s*(ROLLBACK|COMMIT|SAVEPOINT)\b", sql, re.I):
        return sql, "raw"          # transazione: gestita dal runner
    try:
        out = sqlglot.transpile(sql, read="oracle", write="postgres",
                                pretty=False)[0]
        return out, "sqlglot"
    except Exception as e:  # noqa: BLE001
        return None, f"TRANSLATE_FAIL: {type(e).__name__}: {e}"


class PgRunner:
    def __init__(self, conn, baseline):
        import psycopg
        self.conn = conn
        self.conn.autocommit = True
        self.baseline = baseline or {}
        self._in_txn = False

    def _begin_if_needed(self):
        if not self._in_txn:
            self.conn.execute("BEGIN")
            self._in_txn = True

    def execute_pg(self, sql, binds=None):
        cur = self.conn.cursor()
        try:
            cur.execute(sql, binds or None)
            if cur.description:
                cols = [d[0].upper() for d in cur.description]
                rows = norm_rows(cur.fetchall())
                return {"columns": cols, "rows": rows, "rowcount": len(rows),
                        "error": None, "out": None}
            return {"rows": None, "rowcount": cur.rowcount,
                    "error": None, "out": None}
        except Exception as e:  # noqa: BLE001
            sqlstate = getattr(e, "sqlstate", None)
            return {"error": sqlstate or f"PGERR:{type(e).__name__}",
                    "rows": None, "rowcount": None, "out": None,
                    "message": str(e).split("\n")[0]}
        finally:
            cur.close()

    def run_tests(self, tests):
        results = {}
        translations = {}
        for tc in tests:
            if tc.oracle_only:
                results[tc.id] = {"status": "SKIP",
                                  "detail": "oracle-only"}
                continue
            if tc.pg_skip and not tc.pg_sql:
                results[tc.id] = {"status": "SKIP", "detail": tc.pg_skip}
                continue
            self._in_txn = False
            translations[tc.id] = []
            steps_res = []
            ok, detail = True, ""
            for i, step in enumerate(tc.steps):
                sql_pg, origin = to_pg_sql(step, tc)
                translations[tc.id].append({"origin": origin, "sql": sql_pg})
                if sql_pg is None:
                    ok, detail = False, f"step {i}: not translatable ({origin})"
                    steps_res.append({"error": "UNTRANSLATED"})
                    break
                if origin == "raw":
                    self.conn.execute(sql_pg)
                    if sql_pg.strip().upper().startswith(("COMMIT", "ROLLBACK")):
                        self._in_txn = False
                    steps_res.append({"raw_tx": sql_pg})
                    continue
                self._begin_if_needed()
                binds = tc.pg_binds if tc.pg_binds is not None else step.binds
                binds_pg = {k: v for k, v in (binds or {}).items()
                            if k not in step.out_binds}
                res = self.execute_pg(sql_pg, binds_pg)
                steps_res.append(res)
                v = self.verify_step_pg(step, res)
                if not v[0]:
                    ok, detail = False, f"[{origin}] {v[1]}"
                    break
            if self._in_txn:
                self.conn.execute("COMMIT")
                self._in_txn = False
            results[tc.id] = {"status": "PASS" if ok else "FAIL",
                              "detail": detail, "steps": steps_res}
            # confronto con baseline oracle
            base = self.baseline.get(tc.id)
            if base and results[tc.id]["status"] == "PASS":
                if self.matches_baseline(base, results[tc.id]):
                    results[tc.id]["vs_oracle"] = "MATCH"
                else:
                    results[tc.id]["vs_oracle"] = "DIVERGENT"
                    results[tc.id]["detail"] += " | divergent from Oracle"
        return results, translations

    def verify_step_pg(self, step, res):
        if step.expect_error:
            want = PG_SQLSTATE.get(step.expect_error, step.expect_error)
            if res.get("error") != want:
                return False, f"expected {want}, got {res.get('error')}"
            return True, ""
        if res.get("error"):
            return False, f"unexpected error {res['error']}: {res.get('message','')}"
        if step.expect_rows is not None:
            want = norm_rows(step.expect_rows)
            if res.get("rows") != want:
                return False, f"expected rows {want}, got {res.get('rows')}"
        if step.expect_rowcount is not None and res.get("rowcount") != step.expect_rowcount:
            return False, f"expected rowcount {step.expect_rowcount}, got {res.get('rowcount')}"
        return True, ""

    def matches_baseline(self, base, res):
        """Tolerant comparison: DML/transactional steps without rows are
        already verified by their own expectations; the Oracle RETURNING INTO
        (OUT bind) is semantically the PG RETURNING resultset."""
        for bs, rs in zip(base.get("steps", []), res.get("steps", [])):
            if "raw_tx" in rs:
                continue
            b_err, r_err = bs.get("error"), rs.get("error")
            if b_err or r_err:
                if PG_SQLSTATE.get(b_err, b_err) != r_err:
                    return False
                continue
            if bs.get("out") is not None:
                got_rows = rs.get("rows")
                if not got_rows:
                    return False
                vals = list(bs["out"].values())
                if norm_value(vals) != got_rows[0]:
                    return False
                continue
            if bs.get("rows") is not None:
                if bs["rows"] != rs.get("rows"):
                    return False
        return True


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
def write_report(path, mode, results, translations=None, banner=""):
    lines = [f"# OracleBridge smoke test — mode: {mode}",
             f"Generated: {datetime.now().isoformat(timespec='seconds')}",
             f"Database: {banner}", ""]
    if translations is not None:
        lines += ["## Applied translations (sqlglot / override)", ""]
        for tc_id, trs in translations.items():
            for t in trs:
                if t.get("sql") and t.get("origin") in ("sqlglot", "override"):
                    lines.append(f"- `{tc_id}` ({t['origin']}): `{t['sql']}`")
        lines.append("")
    by_status = {}
    for tc_id, r in results.items():
        by_status.setdefault(r["status"], []).append(tc_id)
    lines.append(f"## Summary: " + ", ".join(
        f"{k}={len(v)}" for k, v in sorted(by_status.items())) + "")
    for k in by_status:
        if k == "PASS":
            lines.append(f"- **PASS**: {len(by_status[k])}")
        else:
            lines.append(f"- **{k}**: {len(by_status[k])} -> {', '.join(by_status[k])}")
    lines.append("")
    lines.append("| Test | Stato | Dettaglio |")
    lines.append("|------|-------|-----------|")
    for tc_id, r in results.items():
        extra = f" vs oracle: {r['vs_oracle']}" if r.get("vs_oracle") else ""
        d = (r.get("detail") or "").replace("|", "\\|")[:120] + extra
        lines.append(f"| {tc_id} | {r['status']} | {d} |")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


def summary_print(results):
    ok = sum(1 for r in results.values() if r["status"] == "PASS")
    tot = len(results)
    print(f"\n===== RESULT: {ok}/{tot} PASS =====")
    for tc_id, r in results.items():
        if r["status"] != "PASS":
            print(f"  {r['status']:>6} {tc_id}: {r.get('detail','')}")
    bad = [tc_id for tc_id, r in results.items()
           if r.get("vs_oracle") == "DIVERGENT"]
    if bad:
        print(f"  divergent from Oracle: {', '.join(bad)}")


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["oracle", "postgres", "proxy"],
                    default="oracle")
    ap.add_argument("--filter", default=None,
                    help="run only the tests whose id contains this string")
    args = ap.parse_args()

    tests = [t for t in TESTS if not args.filter or args.filter in t.id]

    Path(RESULTS_DIR).mkdir(parents=True, exist_ok=True)

    if args.mode in ("oracle", "proxy"):
        cfg = ORACLE if args.mode == "oracle" else PROXY
        print(f"Connecting to {cfg.dsn} (user {cfg.user}) ...")
        conn = oracledb.connect(user=cfg.user, password=cfg.password,
                                dsn=cfg.dsn)
        banner = ""
        if args.mode == "oracle":
            with conn.cursor() as c:
                c.execute("select banner from v$version where rownum = 1")
                banner = c.fetchone()[0]
        runner = OraRunner(conn, args.mode)
        results = runner.run_tests(tests)
        conn.close()
        if args.mode == "oracle":
            BASELINE.write_text(json.dumps(results, indent=1, default=str),
                                encoding="utf-8")
        else:
            base = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
            for tc_id, r in results.items():
                b = base.get(tc_id)
                if b and r["status"] == "PASS":
                    same = all(
                        bs.get(k) == rs.get(k)
                        for bs, rs in zip(b.get("steps", []), r["steps"])
                        for k in ("rows", "rowcount", "error", "out")
                    )
                    r["vs_oracle"] = "MATCH" if same else "DIVERGENT"
                else:
                    r["vs_oracle"] = "N/A"
        write_report(Path(RESULTS_DIR) / f"report_{args.mode}.md", args.mode,
                     results, banner=banner)
    else:
        import psycopg
        conn = psycopg.connect(host=POSTGRES.host, port=POSTGRES.port,
                               dbname=POSTGRES.dbname, user=POSTGRES.user,
                               password=POSTGRES.password)
        conn.autocommit = True
        banner = conn.execute("select version()").fetchone()[0]
        base = json.loads(BASELINE.read_text()) if BASELINE.exists() else None
        runner = PgRunner(conn, base)
        results, translations = runner.run_tests(tests)
        conn.close()
        write_report(Path(RESULTS_DIR) / "report_postgres.md", "postgres",
                     results, translations=translations, banner=banner)

    summary_print(results)


if __name__ == "__main__":
    main()
