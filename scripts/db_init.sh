#!/usr/bin/env bash
# Provision the database (db, schemas, roles) by running sql/00_init.sql.
# Role passwords are taken from .env (PGPASSWORD, GRAFANA_PASSWORD) and passed
# to psql via the environment, so no secrets live in the SQL file.
#
# Usage:   ./scripts/db_init.sh
# Auth:    runs psql as the postgres superuser via sudo (prompts once).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
get() { sed -n "s/^$1=//p" "$ROOT/.env" 2>/dev/null | head -1; }

WRITER_PW="${PGPASSWORD:-$(get PGPASSWORD)}"
GRAFANA_PW="${GRAFANA_PASSWORD:-$(get GRAFANA_PASSWORD)}"
: "${WRITER_PW:?set PGPASSWORD in .env}"
: "${GRAFANA_PW:?set GRAFANA_PASSWORD in .env}"

echo "Provisioning database (roles' passwords sourced from .env)"
# Pipe SQL via stdin (opened by this shell) so the postgres OS user need not read
# files inside the home directory, which it usually can't traverse.
sudo -u postgres env PGPASSWORD="$WRITER_PW" GRAFANA_PASSWORD="$GRAFANA_PW" \
    psql -v ON_ERROR_STOP=1 < "$ROOT/sql/00_init.sql"

# Apply the table schemas (no secrets; run as postgres for default privileges).
sudo -u postgres psql -v ON_ERROR_STOP=1 -d robot_data < "$ROOT/sql/01_robot.sql"
sudo -u postgres psql -v ON_ERROR_STOP=1 -d robot_data < "$ROOT/sql/02_vision.sql"

echo "Done: database robot_data, schemas robot/vision, roles robot_writer + grafana_ro."
