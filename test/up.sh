#!/usr/bin/env bash
# OracleBridge test: porta su gli ambienti ed esegue la suite completa.
# Richiede docker funzionante (vedi README).
set -euo pipefail
cd "$(dirname "$0")"

echo "== [1/5] Starting containers (Oracle 26ai Free + PostgreSQL 17) =="
docker compose -f docker/docker-compose.yml up -d --build

echo "== [2/5] Oracle setup (DB wait + schema) =="
python3 scripts/setup_oracle.py

echo "== [3/5] PostgreSQL mirror setup =="
python3 scripts/setup_postgres.py

echo "== [4/5] Smoke test on Oracle (baseline) =="
python3 scripts/smoke_test.py --mode oracle

echo "== [5/5] Diagnostic smoke test on PostgreSQL =="
python3 scripts/smoke_test.py --mode postgres

echo ""
echo "Reports: test/results/report_oracle.md, test/results/report_postgres.md"
echo "When the proxy exists: python3 scripts/smoke_test.py --mode proxy"
