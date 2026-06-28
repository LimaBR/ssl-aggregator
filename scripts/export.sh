#!/usr/bin/env bash
# Export the captured dataset as CSV (one file per table) for offline analysis,
# then bundle into a single .tar.gz to copy to another machine.
#
# Usage:   ./scripts/export.sh [output_dir]
# Auth:    connects as the writer role; password from PGPASSWORD, falling back
#          to PGPASSWORD in .env.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUTDIR="${1:-export_$(date +%Y%m%d_%H%M%S)}"
DB="${EXPORT_DB:-robot_data}"

: "${PGPASSWORD:=$(sed -n 's/^PGPASSWORD=//p' "$ROOT/.env" 2>/dev/null | head -1)}"
export PGPASSWORD
: "${PGPASSWORD:?set PGPASSWORD in .env or the environment}"
CONN="host=localhost dbname=${DB} user=${EXPORT_USER:-robot_writer}"

mkdir -p "$OUTDIR"
echo "Exporting $DB -> $OUTDIR/"

# Client-side \copy writes to the local filesystem (no server FS access needed).
psql "$CONN" -c "\copy (SELECT * FROM robot.telemetry        ORDER BY packet_id) TO '$OUTDIR/robot_telemetry.csv'        WITH CSV HEADER"
psql "$CONN" -c "\copy (SELECT * FROM vision.robot_detection ORDER BY t_capture) TO '$OUTDIR/vision_robot_detection.csv' WITH CSV HEADER"
psql "$CONN" -c "\copy (SELECT * FROM vision.ball_detection  ORDER BY t_capture) TO '$OUTDIR/vision_ball_detection.csv'  WITH CSV HEADER"

# Row-count manifest so you can sanity-check after transfer.
wc -l "$OUTDIR"/*.csv > "$OUTDIR/MANIFEST.txt"

tar czf "$OUTDIR.tar.gz" -C "$(dirname "$OUTDIR")" "$(basename "$OUTDIR")"
echo "Done: $OUTDIR.tar.gz"
