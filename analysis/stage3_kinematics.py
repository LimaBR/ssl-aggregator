#!/usr/bin/env python3
"""Stage 3 — per-wheel ground speed from the camera (inverse kinematics).

Loads the Stage-2 resampled pose/velocity, and with the differential-drive
kinematics turns the camera body motion into what each wheel *should* have done
over the ground:

    v_ground_left  = v_tangent - v_angular * (track/2)
    v_ground_right = v_tangent + v_angular * (track/2)

(The longitudinal-only tracking-point offset cancels in the tangential term, so
it does not enter here; it is applied only to the normal/skid diagnostic.)

Each is paired with the corresponding encoder speed (wheel0=left, wheel1=right);
the gap between them is the per-wheel slip (ratio + mask come in Stage 4).

Output: analysis/derived/kinematics_<session>.parquet + a per-wheel figure.
Run:  .venv/bin/python analysis/stage3_kinematics.py [--session 17:59] [--zoom spike]
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


def geometry():
    load_dotenv(C.REPO / ".env")
    return (float(os.getenv("GEOM_TRACK_WIDTH_M", "0.384")),
            float(os.getenv("GEOM_TRACKING_OFFSET_LON_M", "-0.060")),
            float(os.getenv("GEOM_TRACKING_OFFSET_LAT_M", "0.0")))


def make_plot(session, df, geom, out, center_mode, center_t=None):
    track, off_lon, _ = geom
    rel = df["t_robot"].to_numpy() - df["t_robot"].iloc[0]
    sp = (df["wheel0_setpoint"].to_numpy() + df["wheel1_setpoint"].to_numpy()) / 2

    if center_t is not None:
        ctr, half = center_t, 3.0
    elif center_mode == "spike":
        metric = np.abs(df["enc_left"].to_numpy() - df["vground_left"].to_numpy())
        ctr, half = rel[int(np.nanargmax(np.where(df["covered"], metric, np.nan)))], 3.0
    else:
        ctr, half = rel[int(np.nanargmax(np.abs(np.diff(sp))))], 4.0
    lo, hi = max(0, ctr - half), min(rel[-1], ctr + half)
    m = (rel >= lo) & (rel <= hi)
    not_cov = ~df["covered"].to_numpy()

    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    for ax, side, vg, en, spc in (
            (axes[0], "LEFT  (wheel0)", "vground_left", "enc_left", "wheel0_setpoint"),
            (axes[1], "RIGHT (wheel1)", "vground_right", "enc_right", "wheel1_setpoint")):
        ax.fill_between(rel[m], -3, 3, where=not_cov[m], color="red", alpha=0.08,
                        step="mid", label="masked (camera gap)")
        ax.plot(rel[m], df[spc].to_numpy()[m], color="gray", lw=1.0, ls=":", label="setpoint")
        ax.plot(rel[m], df[en].to_numpy()[m], color="green", lw=1.1, label="encoder (wheel)")
        ax.plot(rel[m], df[vg].to_numpy()[m], color="tab:blue", lw=1.9,
                label="camera ground speed")
        ax.axhline(0, color="k", lw=0.5); ax.grid(alpha=0.3)
        ax.set_ylim(-2.2, 2.2)
        ax.set_title(f"{side} — setpoint / encoder / camera ground speed   (enc−camera gap = slip)")
        ax.set_ylabel("speed [m/s]"); ax.legend(loc="upper right", ncol=4)
    axes[1].set_xlabel("time since session start [s], robot clock")
    fig.suptitle(f"Stage 3 per-wheel kinematics  ({session})   track={track} m",
                 fontweight="bold")
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    print(f"saved plot -> {out}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", default="17:59")
    ap.add_argument("--zoom", choices=["setpoint", "spike"], default="setpoint")
    ap.add_argument("--center", type=float, default=None,
                    help="center the zoom at this time [s since session start]")
    args = ap.parse_args()

    engine = C.make_engine()
    session = C.resolve_session(engine, args.session)
    tag = str(session).replace(" ", "_").replace(":", "")
    parquet = C.DERIVED / f"resampled_{tag}.parquet"
    if not parquet.exists():
        raise SystemExit(f"missing {parquet} — run stage2_resample.py first")

    res = pd.read_parquet(parquet)
    robot = C.load_robot(engine, session,
                         cols="packet_id, wheel0_speed, wheel1_speed, "
                              "wheel0_setpoint, wheel1_setpoint")
    df = res.merge(robot, on="packet_id", how="left")

    track, off_lon, off_lat = geometry()
    half = track / 2.0
    # camera-derived per-wheel ground speed (inverse kinematics)
    df["vground_left"] = df["v_tangent"] - df["v_angular"] * half
    df["vground_right"] = df["v_tangent"] + df["v_angular"] * half
    # axle-corrected normal component (skid diagnostic; offset enters only here)
    df["v_normal_axle"] = df["v_normal"] - off_lon * df["v_angular"]
    # encoder per wheel (wheel0 = left, wheel1 = right)
    df["enc_left"] = df["wheel0_speed"]
    df["enc_right"] = df["wheel1_speed"]
    # raw per-wheel slip preview (signed diff; ratio + mask are Stage 4)
    df["slip_left_raw"] = df["enc_left"] - df["vground_left"]
    df["slip_right_raw"] = df["enc_right"] - df["vground_right"]

    cov = df["covered"]
    print(f"session {session}: {len(df)} samples, {100*cov.mean():.1f}% covered")
    for side in ("left", "right"):
        s = df[f"slip_{side}_raw"][cov]
        corr = df[[f"enc_{side}", f"vground_{side}"]][cov].corr().iloc[0, 1]
        print(f"  {side:5}: enc↔camera corr={corr:.3f}  "
              f"|slip| median={s.abs().median():.3f}  max={s.abs().max():.3f} m/s")

    outp = C.DERIVED / f"kinematics_{tag}.parquet"
    df.to_parquet(outp, index=False)
    print(f"saved data -> {outp}")
    suffix = f"t{args.center:.0f}" if args.center is not None else args.zoom
    make_plot(session, df, (track, off_lon, off_lat),
              C.FIGDIR / f"stage3_kinematics_{tag}_{suffix}.png", args.zoom, args.center)


if __name__ == "__main__":
    main()
