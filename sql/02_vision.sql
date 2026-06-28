-- =============================================================================
-- ssl-aggregator : SSL-Vision schema
-- Run after 00_init.sql, as a superuser:
--     sudo -u postgres psql -d robot_data -f sql/02_vision.sql
-- =============================================================================
\connect robot_data

-- One row per detected robot, per detection frame, per camera.
-- Source: SSL_DetectionFrame on UDP multicast 224.5.23.2:10006.
CREATE TABLE IF NOT EXISTS vision.robot_detection (
    id            BIGSERIAL PRIMARY KEY,
    rx_wall       TIMESTAMPTZ      NOT NULL,  -- when our logger received the frame
    rx_monotonic  DOUBLE PRECISION,
    t_capture     DOUBLE PRECISION NOT NULL,  -- camera capture time (align on this)
    t_sent        DOUBLE PRECISION,
    frame_number  BIGINT,
    camera_id     INT,
    team          SMALLINT,                    -- 0 = blue, 1 = yellow
    robot_id      INT,
    x             REAL,                        -- mm, field frame
    y             REAL,                        -- mm, field frame
    orientation   REAL,                        -- rad
    confidence    REAL
);

CREATE INDEX IF NOT EXISTS robot_detection_t_capture_idx
    ON vision.robot_detection (t_capture);
CREATE INDEX IF NOT EXISTS robot_detection_rx_wall_idx
    ON vision.robot_detection (rx_wall);

-- One row per detected ball, per detection frame, per camera.
-- The robot's orange sync LED appears here as a "ball" when lit -> this is the
-- camera-side copy of robot.telemetry.led_state used for time alignment.
CREATE TABLE IF NOT EXISTS vision.ball_detection (
    id            BIGSERIAL PRIMARY KEY,
    rx_wall       TIMESTAMPTZ      NOT NULL,
    rx_monotonic  DOUBLE PRECISION,
    t_capture     DOUBLE PRECISION NOT NULL,
    t_sent        DOUBLE PRECISION,
    frame_number  BIGINT,
    camera_id     INT,
    x             REAL,                        -- mm
    y             REAL,                        -- mm
    confidence    REAL
);

CREATE INDEX IF NOT EXISTS ball_detection_t_capture_idx
    ON vision.ball_detection (t_capture);
CREATE INDEX IF NOT EXISTS ball_detection_rx_wall_idx
    ON vision.ball_detection (rx_wall);
