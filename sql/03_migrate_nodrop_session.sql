-- =============================================================================
-- Migration: no-drop + capture_session (apply once to an existing robot_data).
--   sudo -u postgres psql -d robot_data -f sql/03_migrate_nodrop_session.sql
-- =============================================================================
\connect robot_data
BEGIN;

-- 1. No-drop: remove the unique index on packet_id (it silently dropped data
--    across firmware reboots, since packet_id restarts at 0 each boot).
DROP INDEX IF EXISTS robot.telemetry_packet_id_uidx;

-- 2. Add the capture_session column (logger start time; one value per run).
ALTER TABLE robot.telemetry ADD COLUMN IF NOT EXISTS capture_session TIMESTAMPTZ;

-- 3. Backfill the three existing captures by their run windows.
UPDATE robot.telemetry SET capture_session = '2026-06-28 14:39:11-03'
 WHERE capture_session IS NULL AND rx_wall >= '2026-06-28 14:39' AND rx_wall < '2026-06-28 14:51';
UPDATE robot.telemetry SET capture_session = '2026-06-28 14:59:03-03'
 WHERE capture_session IS NULL AND rx_wall >= '2026-06-28 14:59' AND rx_wall < '2026-06-28 15:08';
UPDATE robot.telemetry SET capture_session = '2026-06-28 19:52:55-03'
 WHERE capture_session IS NULL AND rx_wall >= '2026-06-28 19:52' AND rx_wall < '2026-06-28 20:06';

-- 4. New non-unique index for ordering/segmenting by run.
CREATE INDEX IF NOT EXISTS telemetry_session_packet_idx
    ON robot.telemetry (capture_session, packet_id);

COMMIT;
