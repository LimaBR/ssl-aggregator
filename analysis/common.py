"""Shared helpers for the slip-analysis pipeline: DB access, session resolution,
data loading, and the LED<->ball time-sync fit (Stage 1)."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PACKET_DT = 0.01  # firmware cadence: one telemetry packet every 10 ms
REPO = Path(__file__).resolve().parent.parent
FIGDIR = REPO / "analysis" / "figures"
DERIVED = REPO / "analysis" / "derived"


# --------------------------------------------------------------------------- #
# DB access + session selection
# --------------------------------------------------------------------------- #
def make_engine():
    """Read-only engine as grafana_ro, credentials from .env."""
    load_dotenv(REPO / ".env")
    user = os.getenv("ANALYSIS_DB_USER", "grafana_ro")
    pw = os.getenv("GRAFANA_PASSWORD")
    host = os.getenv("ANALYSIS_DB_HOST", "localhost")
    db = os.getenv("ANALYSIS_DB_NAME", "robot_data")
    if not pw:
        raise SystemExit("GRAFANA_PASSWORD not set in .env")
    return create_engine(f"postgresql+psycopg://{user}:{pw}@{host}/{db}")


def list_sessions(engine) -> pd.DataFrame:
    return pd.read_sql(
        text("SELECT capture_session, count(*) AS rows, "
             "min(rx_wall) AS t0, max(rx_wall) AS t1 "
             "FROM robot.telemetry WHERE capture_session IS NOT NULL "
             "GROUP BY capture_session ORDER BY capture_session"),
        engine,
    )


def resolve_session(engine, needle: str):
    sessions = list_sessions(engine)
    if sessions.empty:
        raise SystemExit("no capture_session values found (run the migration?)")
    m = sessions[sessions["capture_session"].astype(str).str.contains(needle)]
    if len(m) != 1:
        print(sessions.to_string(index=False))
        raise SystemExit(f"--session '{needle}' matched {len(m)} sessions; be specific")
    return m.iloc[0]["capture_session"]


def to_epoch(s: pd.Series) -> np.ndarray:
    """tz-aware timestamps -> float epoch seconds."""
    return ((s - pd.Timestamp("1970-01-01", tz="UTC")) / pd.Timedelta(seconds=1)).to_numpy()


# physically-plausible telemetry ranges; values outside are corrupt (bad sscanf
# in the firmware, e.g. the occasional garbage setpoint). Set well beyond the
# real signal ranges (measured: speed ±1.6, setpoint ±2, accel ±7, gyro ±366 °/s)
# so only true garbage is caught -- NOT legitimate fast-spin gyro data.
TELEMETRY_LIMITS = {"wheel0_speed": 8.0, "wheel1_speed": 8.0,
                    "wheel0_setpoint": 8.0, "wheel1_setpoint": 8.0,
                    "imu_accel_x": 60.0, "imu_accel_y": 60.0, "imu_gyro_z": 1000.0}


def clean_telemetry(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Repair physically-implausible telemetry as outliers: mark out-of-range
    values NaN, then forward/back-fill. Setpoints are held commands, so the last
    valid value is a principled estimate (not a clipped boundary). `df` must be
    time-ordered. Returns (cleaned_df, n_repaired)."""
    df = df.copy()
    n = 0
    for c, lim in TELEMETRY_LIMITS.items():
        if c not in df.columns:
            continue
        bad = df[c].abs() > lim
        if bad.any():
            n += int(bad.sum())
            df.loc[bad, c] = np.nan
            df[c] = df[c].ffill().bfill()
    return df, n


# --------------------------------------------------------------------------- #
# Loaders
# --------------------------------------------------------------------------- #
def load_robot(engine, session, cols="packet_id, led_state, rx_wall"):
    return pd.read_sql(
        text(f"SELECT {cols} FROM robot.telemetry "
             "WHERE capture_session = :s ORDER BY packet_id"),
        engine, params={"s": session},
    )


def load_ball(engine, t0, t1):
    return pd.read_sql(
        text("SELECT t_capture, rx_wall FROM vision.ball_detection "
             "WHERE rx_wall BETWEEN :t0 AND :t1 ORDER BY t_capture"),
        engine, params={"t0": t0, "t1": t1},
    )


def load_detection(engine, t0, t1):
    """Robot pose from SSL-Vision (one row per frame; x,y in mm, orientation rad)."""
    return pd.read_sql(
        text("SELECT t_capture, x, y, orientation, confidence "
             "FROM vision.robot_detection "
             "WHERE rx_wall BETWEEN :t0 AND :t1 ORDER BY t_capture"),
        engine, params={"t0": t0, "t1": t1},
    )


# --------------------------------------------------------------------------- #
# Time-sync (Stage 1)
# --------------------------------------------------------------------------- #
def led_edges(robot):
    pid = robot["packet_id"].to_numpy()
    led = robot["led_state"].to_numpy()
    t_robot = pid * PACKET_DT
    d = np.diff(led)
    rise = t_robot[np.where(d == 1)[0] + 1]
    fall = t_robot[np.where(d == -1)[0] + 1]
    return rise, fall, t_robot, led


def ball_edges(ball, gap=0.3, min_count=5):
    t = np.sort(ball["t_capture"].to_numpy())
    if t.size == 0:
        return np.array([]), np.array([]), []
    splits = np.where(np.diff(t) > gap)[0]
    starts = np.concatenate(([0], splits + 1))
    ends = np.concatenate((splits, [t.size - 1]))
    rise, fall, intervals = [], [], []
    for s, e in zip(starts, ends):
        if e - s + 1 >= min_count:
            rise.append(t[s]); fall.append(t[e]); intervals.append((t[s], t[e]))
    return np.array(rise), np.array(fall), intervals


def _match(robot_t, cam_t, b0, window=0.5):
    if robot_t.size == 0 or cam_t.size == 0:
        return np.empty(0), np.empty(0)
    cam = np.sort(cam_t)
    xs, ys = [], []
    for rt in robot_t:
        pred = rt + b0
        j = np.searchsorted(cam, pred)
        cands = [cam[k] for k in (j - 1, j) if 0 <= k < cam.size]
        if not cands:
            continue
        best = min(cands, key=lambda c: abs(c - pred))
        if abs(best - pred) <= window:
            xs.append(rt); ys.append(best)
    return np.array(xs), np.array(ys)


def robust_fit(x, y, n_iter=3):
    mask = np.ones(x.size, bool)
    a = b = 0.0
    for _ in range(n_iter):
        a, b = np.polyfit(x[mask], y[mask], 1)
        resid = y - (a * x + b)
        med = np.median(resid[mask])
        mad = 1.4826 * np.median(np.abs(resid[mask] - med))
        if mad == 0:
            break
        mask = np.abs(resid - med) < 3 * mad
    a, b = np.polyfit(x[mask], y[mask], 1)
    resid = y[mask] - (a * x[mask] + b)
    return a, b, resid, mask


def fit_timesync(robot, ball) -> dict:
    """Fit t_capture ≈ a*(packet_id*0.01) + b. Returns fit + diagnostics."""
    r_rise, r_fall, t_robot, led = led_edges(robot)
    c_rise, c_fall, intervals = ball_edges(ball)
    boot = np.median(to_epoch(robot["rx_wall"]) - robot["packet_id"].to_numpy() * PACKET_DT)
    xr, yr = _match(r_rise, c_rise, boot)
    xf, yf = _match(r_fall, c_fall, boot)
    x = np.concatenate([xr, xf]); y = np.concatenate([yr, yf])
    if x.size < 5:
        raise SystemExit(f"only {x.size} edge matches — sync failed, inspect data")
    a, b, resid, mask = robust_fit(x, y)
    dur = t_robot.max() - t_robot.min()
    return dict(
        a=a, b=b, boot=boot, n=int(x.size), kept=int(mask.sum()),
        resid_ms=float(resid.std() * 1e3),
        drift_ms=float((a - 1.0) * dur * 1e3),
        latency_ms=float(np.median(y - (x + boot)) * 1e3),
        intervals=intervals, t_robot=t_robot, led=led, duration=dur,
    )
