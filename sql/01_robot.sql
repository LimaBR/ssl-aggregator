-- =============================================================================
-- ssl-aggregator : robot telemetry schema
-- Run after 00_init.sql, as a superuser:
--     sudo -u postgres psql -d robot_data -f sql/01_robot.sql
-- (Run as postgres so the ALTER DEFAULT PRIVILEGES from 00_init.sql grant
--  access to robot_writer / grafana_ro automatically.)
-- =============================================================================
\connect robot_data

-- One row per telemetry packet received from the robot (sent every 10 ms).
-- Wire format (ASCII, UDP multicast 239.0.0.1:10001):
--   >Speed:<packet_id>,<f0>,<f1>,<f2>,<f3>,<f4>,<f5>,<f6>,<led>
CREATE TABLE IF NOT EXISTS robot.telemetry (
    id              BIGSERIAL PRIMARY KEY,
    rx_wall         TIMESTAMPTZ      NOT NULL,  -- when our logger received it
    rx_monotonic    DOUBLE PRECISION,           -- steady clock (s), for jitter
    packet_id       BIGINT,                     -- uint32 from firmware; gaps = lost pkts
    wheel0_speed    REAL,                        -- mm/s, encoder (slip input)
    wheel1_speed    REAL,                        -- mm/s, encoder (slip input)
    wheel0_setpoint REAL,                        -- mm/s, commanded
    wheel1_setpoint REAL,                        -- mm/s, commanded
    imu_accel_x     REAL,
    imu_accel_y     REAL,
    imu_gyro_z      REAL,
    led_state       SMALLINT         NOT NULL    -- camera-sync bit (0/1)
);

-- Idempotent / replay-safe: one row per packet_id.
CREATE UNIQUE INDEX IF NOT EXISTS telemetry_packet_id_uidx
    ON robot.telemetry (packet_id);

-- Time-range queries (Grafana dashboards).
CREATE INDEX IF NOT EXISTS telemetry_rx_wall_idx
    ON robot.telemetry (rx_wall);
