#!/usr/bin/env bash
# OracleBridge test: porta su gli ambienti ed esegue la suite completa.
# Richiede docker funzionante (vedi README).
set -euo pipefail
cd "$(dirname "$0")"

echo "== [1/5] Avvio container (Oracle 26ai Free + PostgreSQL 17) =="
docker compose -f docker/docker-compose.yml up -d --build

echo "== [2/5] Setup Oracle (attesa DB + schema) =="
python3 scripts/setup_oracle.py

echo "== [3/5] Setup PostgreSQL mirror =="
python3 scripts/setup_postgres.py

echo "== [4/5] Smoke test su Oracle (baseline) =="
python3 scripts/smoke_test.py --mode oracle

echo "== [5/5] Smoke test diagnostico su PostgreSQL =="
python3 scripts/smoke_test.py --mode postgres

echo ""
echo "Report: test/results/report_oracle.md, test/results/report_postgres.md"
echo "Quando il proxy esiste: python3 scripts/smoke_test.py --mode proxy"
