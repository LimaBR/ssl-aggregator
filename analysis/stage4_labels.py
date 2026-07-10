#!/usr/bin/env python3
"""Stage 4 — per-wheel slip labels.

Primary label = slip VELOCITY (m/s):
    slip_vel = v_encoder - v_ground        (v_ground = camera per-wheel, Stage 3)
> 0 wheel spinning faster than ground (drive slip); < 0 lagging (brake/lock).
It is well-conditioned at all speeds (no division), so a label is valid wherever
the camera has coverage (Stage-2 mask) -- idle just gives slip_vel ≈ 0.

A secondary interpretive slip RATIO is kept too:
    slip_ratio = (v_enc - v_ground)/max(|v_enc|, |v_ground|, eps)
valid only where a wheel is actually moving (else the ratio is ill-conditioned);
|ratio|>1 flags direction-reversal slip.

Combines all sessions into one labeled parquet with the causal robot features.
Run:  .venv/bin/python analysis/stage4_labels.py [--session 17:59 | --all]
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd
from dotenv import load_dotenv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import common as C

FEATURES = ["wheel0_speed", "wheel1_speed", "wheel0_setpoint", "wheel1_setpoint",
            "imu_accel_x", "imu_accel_y", "imu_gyro_z"]
KEEP = (["capture_session", "packet_id", "t_robot", "covered",
         "slip_vel_left", "slip_vel_right", "valid_left", "valid_right",
         "slip_ratio_left", "slip_ratio_right", "ratio_valid_left", "ratio_valid_right"]
        + FEATURES + ["led_state",
                      "enc_left", "enc_right", "vground_left", "vground_right",
                      "v_tangent", "v_angular"])
SLIP_FLAG = 0.20   # |slip_vel| above this counts as "slipping" (reporting only)


def label_session(engine, session, lowspeed):
    tag = str(session).replace(" ", "_").replace(":", "")
    kpath = C.DERIVED / f"kinematics_{tag}.parquet"
    if not kpath.exists():
        raise SystemExit(f"missing {kpath} — run stage3_kinematics.py --session {session}")
    df = pd.read_parquet(kpath)
    feats = C.load_robot(engine, session,
                         cols="packet_id, imu_accel_x, imu_accel_y, imu_gyro_z, led_state")
    df = df.merge(feats, on="packet_id", how="left").sort_values("packet_id")

    df, n_rep = C.clean_telemetry(df)          # repair corrupt telemetry (outliers)
    if n_rep:
        print(f"  {session}: repaired {n_rep} corrupt telemetry values")

    for side in ("left", "right"):
        e, g = df[f"enc_{side}"], df[f"vground_{side}"]
        df[f"slip_vel_{side}"] = e - g                          # primary label (m/s)
        df[f"valid_{side}"] = df["covered"] & np.isfinite(e - g)
        denom = np.maximum(np.maximum(e.abs(), g.abs()), lowspeed)
        df[f"slip_ratio_{side}"] = (e - g) / denom              # secondary (interpretive)
        moving = np.maximum(e.abs(), g.abs()) >= lowspeed
        df[f"ratio_valid_{side}"] = df[f"valid_{side}"] & moving
    df["capture_session"] = str(session)
    return df[KEEP]


def make_plot(out_df, out):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))
    for side in ("left", "right"):
        v = out_df.loc[out_df[f"valid_{side}"], f"slip_vel_{side}"].clip(-1.5, 1.5)
        ax1.hist(v, bins=120, histtype="step", lw=1.6, label=f"{side} wheel")
    for x in (SLIP_FLAG, -SLIP_FLAG):
        ax1.axvline(x, color="gray", ls=":")
    ax1.set_yscale("log"); ax1.set_xlabel("slip velocity [m/s]"); ax1.set_ylabel("count (log)")
    ax1.set_title("Per-wheel slip-velocity distribution (valid labels)")
    ax1.grid(alpha=0.3); ax1.legend()

    ses = out_df["capture_session"].unique()[0]
    d = out_df[out_df["capture_session"] == ses]
    rel = d["t_robot"].to_numpy() - d["t_robot"].to_numpy()[0]
    for side, c in (("left", "tab:blue"), ("right", "tab:orange")):
        sv = d[f"slip_vel_{side}"].where(d[f"valid_{side}"]).to_numpy()
        ax2.plot(rel, sv, lw=0.5, color=c, alpha=0.8, label=side)
    ax2.axhline(0, color="k", lw=0.5)
    ax2.set_xlabel("time [s]"); ax2.set_ylabel("slip velocity [m/s]")
    ax2.set_title(f"Slip velocity over time — {ses}"); ax2.grid(alpha=0.3); ax2.legend()

    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    print(f"saved plot -> {out}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", default="17:59")
    ap.add_argument("--all", action="store_true", help="process and combine all sessions")
    args = ap.parse_args()
    load_dotenv(C.REPO / ".env")
    lowspeed = float(os.getenv("ANALYSIS_LOWSPEED_MASK_MPS", "0.05"))

    engine = C.make_engine()
    sessions = (list(C.list_sessions(engine)["capture_session"]) if args.all
                else [C.resolve_session(engine, args.session)])
    out_df = pd.concat([label_session(engine, s, lowspeed) for s in sessions],
                       ignore_index=True)

    print(f"{'session':26} {'rows':>7} {'valid':>7} {'med|sv|':>8} "
          f"{'p99|sv|':>8} {'max|sv|':>8} {'slip%':>7}")
    for s in sessions:
        d = out_df[out_df["capture_session"] == str(s)]
        v = d["valid_left"]; sv = d.loc[v, "slip_vel_left"].abs()
        print(f"{str(s):26} {len(d):7d} {v.mean():6.1%} {sv.median():8.3f} "
              f"{sv.quantile(.99):8.3f} {sv.max():8.3f} {(sv > SLIP_FLAG).mean():6.1%}")

    outp = C.DERIVED / "slip_labels.parquet"
    out_df.to_parquet(outp, index=False)
    print(f"\nsaved labeled dataset -> {outp}  ({len(out_df)} rows, {len(KEEP)} cols)")
    make_plot(out_df, C.FIGDIR / "stage4_slip_labels.png")


if __name__ == "__main__":
    main()
