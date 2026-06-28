#!/usr/bin/env bash
# Full logical dump of the dataset database (custom format), for restoring into
# Postgres on another machine with scripts/db_restore.sh.
#
# Usage:   ./scripts/db_dump.sh [output_file]
# Auth:    connects over TCP as the writer role (needs SELECT on sequences,
#          which grafana_ro lacks); password from PGPASSWORD, defaulting to the
#          .env writer password.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DB="${EXPORT_DB:-robot_data}"
OUT="${1:-${DB}_$(date +%Y%m%d_%H%M%S).dump}"

# Password comes from the environment, falling back to PGPASSWORD in .env.
: "${PGPASSWORD:=$(sed -n 's/^PGPASSWORD=//p' "$ROOT/.env" 2>/dev/null | head -1)}"
export PGPASSWORD
: "${PGPASSWORD:?set PGPASSWORD in .env or the environment}"
CONN="host=localhost dbname=${DB} user=${EXPORT_USER:-robot_writer}"

echo "Dumping ${DB} -> ${OUT} (custom format)"
# Write to stdout and redirect, so the file is owned by the current user.
# --no-owner/--no-privileges keep the dump portable (no robot_writer/grafana_ro
# role references), so it restores cleanly on a machine without those roles.
pg_dump -Fc --no-owner --no-privileges "$CONN" > "$OUT"

ls -lh "$OUT"
echo "Done. Copy ${OUT} to the other machine, then: ./scripts/db_restore.sh ${OUT}"
