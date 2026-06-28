#!/usr/bin/env bash
# Restore a dump produced by scripts/db_dump.sh into a local Postgres. Creates
# the target database if it does not exist. Run this on the analysis machine.
#
# Usage:   ./scripts/db_restore.sh <dump-file> [dbname]
# Auth:    uses the postgres superuser via sudo (standard on a fresh install);
#          prompts for your sudo password once.
set -euo pipefail

DUMP="${1:?usage: db_restore.sh <dump-file> [dbname]}"
DB="${2:-robot_data}"
[ -f "$DUMP" ] || { echo "no such file: $DUMP" >&2; exit 1; }

echo "Restoring ${DUMP} -> database ${DB}"

# Create the database if missing.
if ! sudo -u postgres psql -tAc \
        "SELECT 1 FROM pg_database WHERE datname='${DB}'" | grep -q 1; then
    echo "creating database ${DB}"
    sudo -u postgres createdb "$DB"
fi

# Pipe the dump in via stdin so the postgres user need not traverse your home
# directory to read the file.
sudo -u postgres pg_restore --no-owner --no-privileges -d "$DB" < "$DUMP"

echo "Done. Data restored into ${DB} (schemas robot, vision)."
echo "To also run the loggers/Grafana here, apply sql/00_init.sql first to create the roles."
