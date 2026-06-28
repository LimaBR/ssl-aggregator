-- =============================================================================
-- ssl-aggregator : database provisioning
-- =============================================================================
-- Creates:
--   * database  robot_data
--   * schemas   robot   (App 1 - robot telemetry)
--               vision  (App 2 - SSL-Vision detections)
--   * roles     robot_writer  (LOGIN) - used by the two C++ loggers (read/write)
--               grafana_ro    (LOGIN) - used by Grafana (read-only)
--
-- Role passwords are read from the environment (no secrets in this file).
-- Run via the wrapper, which loads them from .env:
--     ./scripts/db_init.sh
-- or manually:
--     sudo -u postgres env PGPASSWORD=... GRAFANA_PASSWORD=... \
--         psql -v ON_ERROR_STOP=1 -f sql/00_init.sql
--
-- This script is idempotent: re-running it will not error on existing objects.
-- =============================================================================

-- Pull passwords from environment variables into psql variables.
\getenv writer_password  PGPASSWORD
\getenv grafana_password GRAFANA_PASSWORD

-- ----------------------------------------------------------------------------
-- 1. Roles (cluster-global; created while connected to the maintenance DB)
-- ----------------------------------------------------------------------------
-- NOTE: psql does NOT interpolate :variables inside dollar-quoted ($$) blocks,
-- so role creation is done with \gexec (interpolation happens at the psql level).
SELECT format('CREATE ROLE robot_writer LOGIN PASSWORD %L', :'writer_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'robot_writer')
\gexec

SELECT format('CREATE ROLE grafana_ro LOGIN PASSWORD %L', :'grafana_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_ro')
\gexec

-- Keep passwords in sync with this script even if the role already existed.
ALTER ROLE robot_writer PASSWORD :'writer_password';
ALTER ROLE grafana_ro   PASSWORD :'grafana_password';

-- ----------------------------------------------------------------------------
-- 2. Database (CREATE DATABASE cannot run in a transaction or IF NOT EXISTS,
--    so guard it with \gexec)
-- ----------------------------------------------------------------------------
SELECT 'CREATE DATABASE robot_data OWNER postgres'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'robot_data')
\gexec

-- Lock down who may connect.
REVOKE CONNECT ON DATABASE robot_data FROM PUBLIC;
GRANT  CONNECT ON DATABASE robot_data TO robot_writer, grafana_ro;

-- ----------------------------------------------------------------------------
-- 3. Switch into the new database for schema + privilege setup
-- ----------------------------------------------------------------------------
\connect robot_data

CREATE SCHEMA IF NOT EXISTS robot;
CREATE SCHEMA IF NOT EXISTS vision;

-- USAGE lets a role "see into" the schema; it does not grant table access.
GRANT USAGE ON SCHEMA robot, vision TO robot_writer, grafana_ro;

-- ----------------------------------------------------------------------------
-- 4. Default privileges for tables/sequences created LATER by postgres.
--    (Migration files in sql/ are run as postgres, so these apply to them.)
-- ----------------------------------------------------------------------------
-- Writer: full DML on tables + use of BIGSERIAL sequences.
ALTER DEFAULT PRIVILEGES IN SCHEMA robot, vision
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO robot_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA robot, vision
    GRANT USAGE, SELECT ON SEQUENCES TO robot_writer;

-- Grafana: read-only.
ALTER DEFAULT PRIVILEGES IN SCHEMA robot, vision
    GRANT SELECT ON TABLES TO grafana_ro;

-- ----------------------------------------------------------------------------
-- 5. Apply the same grants to any tables that ALREADY exist (re-run safety).
-- ----------------------------------------------------------------------------
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA robot, vision TO robot_writer;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA robot, vision TO robot_writer;
GRANT SELECT                         ON ALL TABLES    IN SCHEMA robot, vision TO grafana_ro;

\echo ''
\echo '  Provisioning complete:'
\echo '    database : robot_data'
\echo '    schemas  : robot, vision'
\echo '    roles    : robot_writer (rw), grafana_ro (ro)'
\echo ''
