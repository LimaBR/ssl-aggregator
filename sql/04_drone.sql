-- =============================================================================
-- ssl-aggregator : drone schema (dji-relay, DJI Mini 3 Pro live video + messages)
-- Run after 00_init.sql, as a superuser:
--     sudo -u postgres psql -v ON_ERROR_STOP=1 -d robot_data < sql/04_drone.sql
-- (stdin, so the postgres user need not read files in the home directory)
-- Safe to re-run. Creates the schema and its grants itself, so an existing
-- database does not need 00_init.sql again.
-- Written by drone_logger (see dji-relay docs/specification.md 8.4 and
-- docs/protocol.md for the messages).
-- =============================================================================
\connect robot_data

CREATE SCHEMA IF NOT EXISTS drone;
GRANT USAGE ON SCHEMA drone TO robot_writer, grafana_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA drone
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO robot_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA drone
    GRANT USAGE, SELECT ON SEQUENCES TO robot_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA drone
    GRANT SELECT ON TABLES TO grafana_ro;

-- One row per access unit assembled from RTP (UDP 5600).
-- rx_* = first packet; inject_* = handed to v4l2sink (NULL if not decoded/injected).
CREATE TABLE IF NOT EXISTS drone.live_frame (
    id                  BIGSERIAL PRIMARY KEY,
    rx_wall             TIMESTAMPTZ      NOT NULL,
    rx_monotonic        DOUBLE PRECISION,
    capture_session     TIMESTAMPTZ,
    ssrc                BIGINT,
    segment             INT,
    frame_idx           BIGINT,
    rtp_ts              BIGINT,
    seq_first           INT,
    seq_last            INT,
    n_packets           INT,
    n_lost              INT,
    complete            BOOLEAN,
    key                 BOOLEAN,
    size                INT,                       -- RTP payload bytes
    t_rx_ns             BIGINT,                    -- phone receive time (elapsedRealtimeNanos)
    pts_ms              BIGINT,                    -- presentationTimeMs (UTC epoch ms)
    first_rx_kernel_ns  BIGINT,                    -- kernel receive time, CLOCK_REALTIME ns
    last_rx_kernel_ns   BIGINT,
    last_rx_monotonic   DOUBLE PRECISION,
    inject_wall         TIMESTAMPTZ,
    inject_monotonic    DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS live_frame_session_idx
    ON drone.live_frame (capture_session, segment, frame_idx);
CREATE INDEX IF NOT EXISTS live_frame_rx_wall_idx ON drone.live_frame (rx_wall);

-- One row per `frame` message (UDP 5601): the phone's view of each access unit.
CREATE TABLE IF NOT EXISTS drone.phone_frame (
    id                  BIGSERIAL PRIMARY KEY,
    rx_wall             TIMESTAMPTZ      NOT NULL,
    rx_monotonic        DOUBLE PRECISION,
    capture_session     TIMESTAMPTZ,
    phone_session       TEXT,
    seq                 BIGINT,
    segment             INT,
    frame_idx           BIGINT,
    rtp_ts              BIGINT,
    rtp_seq_first       INT,
    rtp_seq_last        INT,
    t_rx_ns             BIGINT,
    t_tx_ns             BIGINT,
    pts_ms              BIGINT,
    key                 BOOLEAN,
    size                INT,
    nal_types           INT[],
    sei_count           INT,
    sei_types           INT[],
    w                   INT,
    h                   INT,
    fps                 INT,
    mime                TEXT
);
CREATE INDEX IF NOT EXISTS phone_frame_session_idx
    ON drone.phone_frame (capture_session, segment, frame_idx);
CREATE INDEX IF NOT EXISTS phone_frame_rx_wall_idx ON drone.phone_frame (rx_wall);

-- One row per `telemetry` message: one key update.
CREATE TABLE IF NOT EXISTS drone.telemetry (
    id                  BIGSERIAL PRIMARY KEY,
    rx_wall             TIMESTAMPTZ      NOT NULL,
    rx_monotonic        DOUBLE PRECISION,
    capture_session     TIMESTAMPTZ,
    phone_session       TEXT,
    seq                 BIGINT,
    t_ph_ns             BIGINT,
    key                 TEXT,
    value               JSONB
);
CREATE INDEX IF NOT EXISTS telemetry_key_idx ON drone.telemetry (capture_session, key, t_ph_ns);
CREATE INDEX IF NOT EXISTS telemetry_rx_wall_idx ON drone.telemetry (rx_wall);

-- One row per `event` or `key_rates` message. payload = the whole message.
CREATE TABLE IF NOT EXISTS drone.event (
    id                  BIGSERIAL PRIMARY KEY,
    rx_wall             TIMESTAMPTZ      NOT NULL,
    rx_monotonic        DOUBLE PRECISION,
    capture_session     TIMESTAMPTZ,
    phone_session       TEXT,
    seq                 BIGINT,
    t_ph_ns             BIGINT,
    type                TEXT,                      -- event name, or 'key_rates'
    payload             JSONB
);
CREATE INDEX IF NOT EXISTS event_rx_wall_idx ON drone.event (rx_wall);

-- One row per `clock` beacon (10 Hz). d = rx_kernel_ns - t_ph_ns = offset + one-way delay.
CREATE TABLE IF NOT EXISTS drone.clock_beacon (
    id                  BIGSERIAL PRIMARY KEY,
    rx_wall             TIMESTAMPTZ      NOT NULL,
    rx_monotonic        DOUBLE PRECISION,
    capture_session     TIMESTAMPTZ,
    phone_session       TEXT,
    seq                 BIGINT,
    t_ph_ns             BIGINT,                    -- phone elapsedRealtimeNanos, right before sendto
    rx_kernel_ns        BIGINT                     -- PC kernel receive time, CLOCK_REALTIME ns
);
CREATE INDEX IF NOT EXISTS clock_beacon_session_idx ON drone.clock_beacon (capture_session, seq);
CREATE INDEX IF NOT EXISTS clock_beacon_rx_wall_idx ON drone.clock_beacon (rx_wall);

-- One row per checked field each time the reported value changes (spec 8.5).
CREATE TABLE IF NOT EXISTS drone.config_check (
    id                  BIGSERIAL PRIMARY KEY,
    rx_wall             TIMESTAMPTZ      NOT NULL,
    rx_monotonic        DOUBLE PRECISION,
    capture_session     TIMESTAMPTZ,
    field               TEXT,
    expected            TEXT,
    reported            TEXT,
    ok                  BOOLEAN
);
CREATE INDEX IF NOT EXISTS config_check_rx_wall_idx ON drone.config_check (rx_wall);

-- Grants for tables that already exist (re-run safety).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES    IN SCHEMA drone TO robot_writer;
GRANT USAGE, SELECT                  ON ALL SEQUENCES IN SCHEMA drone TO robot_writer;
GRANT SELECT                         ON ALL TABLES    IN SCHEMA drone TO grafana_ro;
