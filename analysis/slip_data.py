"""Slip-model data layer — the single source of feature/label construction.

Two representations come out of the same labelled parquet (Stages 1–4):

  * tabular  — `load_examples()`: causal 200 ms window features per wheel, with
    a temporal dev/test split. Consumed by the tabular models (kNN/RF/XGB/MLP).
  * sequence — `esn_sequences()`: raw per-session signal streams. Consumed by the
    ESN, which is stateful and needs the time series, not a windowed table.

Everything downstream (harness, model cards, drivers) imports its constants and
loaders from here.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

import common as C

# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #
W = 20            # causal window length: 200 ms at 100 Hz
DEV_FRAC = 0.80   # first 80% of each session = development; last 20% = final test
SLIP_FLAG = 0.20  # |slip_vel| (m/s) threshold defining the detection view

# side -> (this wheel, other wheel, this setpoint, target, valid mask)
SIDES = {
    "left":  ("wheel0_speed", "wheel1_speed", "wheel0_setpoint", "slip_vel_left", "valid_left"),
    "right": ("wheel1_speed", "wheel0_speed", "wheel1_setpoint", "slip_vel_right", "valid_right"),
}

# tabular feature columns (order matters — models consume the numpy view)
FEATURES = ["w", "w_other", "sp", "sp_err", "ax", "ay", "gz",
            "w_mean", "w_std", "sp_mean", "ax_std", "ay_std", "gz_std",
            "w_accel", "sp_rate"]

# raw signals fed to the ESN (per side); the ESN input dimension follows from it
ESN_N_IN = 7

_LABELS = C.DERIVED / "slip_labels.parquet"
_BEST = C.DERIVED / "best_hparams.json"


# --------------------------------------------------------------------------- #
# tabular representation
# --------------------------------------------------------------------------- #
def build_features(g: pd.DataFrame) -> pd.DataFrame:
    """Causal per-wheel window features for one session (sorted by packet_id).
    Telemetry is already cleaned upstream in Stage 4 (common.clean_telemetry)."""
    ax, ay, gz = g["imu_accel_x"], g["imu_accel_y"], g["imu_gyro_z"]
    rows = []
    for side, (wc, woc, spc, yc, vc) in SIDES.items():
        w, wo, sp = g[wc], g[woc], g[spc]
        d = pd.DataFrame({
            "w": w, "w_other": wo, "sp": sp, "sp_err": sp - w,
            "ax": ax, "ay": ay, "gz": gz,
            "w_mean": w.rolling(W, min_periods=W).mean(),
            "w_std": w.rolling(W, min_periods=W).std(),
            "sp_mean": sp.rolling(W, min_periods=W).mean(),
            "ax_std": ax.rolling(W, min_periods=W).std(),
            "ay_std": ay.rolling(W, min_periods=W).std(),
            "gz_std": gz.rolling(W, min_periods=W).std(),
            "w_accel": (w - w.shift(W)) / (W * C.PACKET_DT),
            "sp_rate": (sp - sp.shift(W)) / (W * C.PACKET_DT),
            "y": g[yc], "valid": g[vc], "session": g["capture_session"],
            "split": g["split"], "side": side, "packet_id": g["packet_id"],
        })
        rows.append(d)
    return pd.concat(rows)


def load_examples() -> pd.DataFrame:
    """Tabular examples for every session, tagged split='dev'|'test' by the
    temporal 80/20 cut. Rows with incomplete windows or no camera coverage are
    dropped. Callers select dev/test via the 'split' column."""
    df = pd.read_parquet(_LABELS)
    parts = []
    for _, g in df.groupby("capture_session"):
        g = g.sort_values("packet_id").reset_index(drop=True)
        cut = g["packet_id"].quantile(DEV_FRAC)
        g["split"] = np.where(g["packet_id"] <= cut, "dev", "test")
        parts.append(build_features(g))
    ex = pd.concat(parts, ignore_index=True)
    ex = ex.dropna(subset=FEATURES + ["y"])
    return ex[ex["valid"]]


# --------------------------------------------------------------------------- #
# sequence representation (ESN)
# --------------------------------------------------------------------------- #
def esn_sequences(split: str = "dev") -> dict:
    """Per-session raw signal streams for the ESN.

    split: 'dev' (first 80%), 'test' (last 20%), or 'all'. Returns
    {session: {side: (U[T,7], y[T], valid[T])}} with U columns
    [w, w_other, setpoint, setpoint_err, accel_x, accel_y, gyro_z]."""
    df = pd.read_parquet(_LABELS)
    seqs = {}
    for ses, g in df.groupby("capture_session"):
        g = g.sort_values("packet_id")
        cut = g["packet_id"].quantile(DEV_FRAC)
        if split == "dev":
            g = g[g["packet_id"] <= cut]
        elif split == "test":
            g = g[g["packet_id"] > cut]
        elif split != "all":
            raise ValueError(f"split must be dev/test/all, got {split!r}")
        g, _ = C.clean_telemetry(g)
        per_side = {}
        for side, (wc, woc, spc, yc, vc) in SIDES.items():
            U = np.column_stack([g[wc], g[woc], g[spc], g[spc] - g[wc],
                                 g["imu_accel_x"], g["imu_accel_y"],
                                 g["imu_gyro_z"]]).astype(np.float32)
            per_side[side] = (U, g[yc].to_numpy(), g[vc].to_numpy().astype(bool))
        seqs[ses] = per_side
    return seqs


# --------------------------------------------------------------------------- #
# tuned-hyperparameter lookup (written by slip_tune)
# --------------------------------------------------------------------------- #
def load_best(model: str, defaults: dict) -> dict:
    """Return tuned params for 'mlp'/'esn' from derived/best_hparams.json, or
    `defaults` if the file (or that entry) is absent. Model cards call this so a
    tuning run automatically feeds compare/final_test."""
    if not _BEST.exists():
        return dict(defaults)
    entry = json.loads(_BEST.read_text()).get(model, {})
    return {**defaults, **entry.get("params", {})}
