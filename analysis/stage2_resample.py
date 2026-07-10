#!/usr/bin/env python3
"""Stage 2 — resample the camera pose onto the robot's 100 Hz packet_id grid.

Using the Stage-1 map t_cam = a*t_robot + b, we fit smoothing splines to the
irregular 60 Hz camera samples (x, y, and cos/sin of orientation) and evaluate
value + derivative directly at the robot grid times. This yields, per robot
sample: resampled pose, body velocity (vx, vy, speed), heading unit vector, and
angular rate omega -- the input to the Stage-3 kinematics.

A Savitzky-Golay velocity (computed on a uniform grid) is overlaid for
comparison so the smoothing can be judged on real data.

Output: analysis/derived/resampled_<session>.parquet  + a comparison figure.
Run:  .venv/bin/python analysis/stage2_resample.py [--session 17:59] [--lam ...]
"""
from __future__ import annotations

import argparse
import os

import numpy as np
import pandas as pd
from scipy.interpolate import make_smoothing_spline
from scipy.signal import savgol_filter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import common as C

ROBOT_COLS = ("packet_id, led_state, rx_wall, "
              "wheel0_speed, wheel1_speed, wheel0_setpoint, wheel1_setpoint")


def _strictly_increasing(t, cols):
    order = np.argsort(t)
    t = t[order]; cols = [c[order] for c in cols]
    keep = np.concatenate(([True], np.diff(t) > 0))
    return t[keep], [c[keep] for c in cols]


def resample(robot, det, fit, lam, sg_win_ms, sg_poly, gap_max_ms):
    a, b = fit["a"], fit["b"]
    pid = robot["packet_id"].to_numpy()
    t_robot = pid * C.PACKET_DT
    t_cam_grid = a * t_robot + b

    tc = det["t_capture"].to_numpy()
    x = det["x"].to_numpy() / 1000.0        # mm -> m
    y = det["y"].to_numpy() / 1000.0
    th = det["orientation"].to_numpy()
    tc, (x, y, c, s) = _strictly_increasing(tc, [x, y, np.cos(th), np.sin(th)])

    inrange = (t_cam_grid >= tc[0]) & (t_cam_grid <= tc[-1])
    # gap mask: a sample is "covered" only if the camera detections bracketing it
    # are within gap_max apart; otherwise the pose would be fabricated -> mask it.
    idx = np.clip(np.searchsorted(tc, t_cam_grid), 1, tc.size - 1)
    bracket_gap = tc[idx] - tc[idx - 1]
    covered = inrange & (bracket_gap <= gap_max_ms / 1e3)
    q = t_cam_grid[covered]

    # --- smoothing splines: value + analytic derivative on the robot grid ---
    def spl(v):
        return make_smoothing_spline(tc, v, lam=lam)
    sx, sy, sc, ss = spl(x), spl(y), spl(c), spl(s)
    X, Y = sx(q), sy(q)
    VX, VY = sx.derivative()(q), sy.derivative()(q)
    C_, S_ = sc(q), ss(q)
    Cd, Sd = sc.derivative()(q), ss.derivative()(q)
    norm2 = C_ ** 2 + S_ ** 2
    v_angular = (C_ * Sd - S_ * Cd) / norm2      # SSL angular [rad/s]: Im(z' conj z)/|z|^2
    norm = np.sqrt(norm2)
    cos_h, sin_h = C_ / norm, S_ / norm
    v_tangent = VX * cos_h + VY * sin_h          # SSL tangential: + along heading, - reverse
    v_normal = -VX * sin_h + VY * cos_h          # SSL normal: sideways skid (should be ~0)
    speed = np.hypot(VX, VY)                      # unsigned magnitude

    n = t_robot.size
    def full(v):
        out = np.full(n, np.nan); out[covered] = v; return out

    df = pd.DataFrame({
        "packet_id": pid, "t_robot": t_robot, "t_cam": t_cam_grid,
        "in_range": inrange, "covered": covered,
        "x_m": full(X), "y_m": full(Y),
        "vx": full(VX), "vy": full(VY),
        "v_tangent": full(v_tangent), "v_normal": full(v_normal), "speed": full(speed),
        "cos_h": full(cos_h), "sin_h": full(sin_h), "v_angular": full(v_angular),
    })

    # --- Savitzky-Golay comparison: SG on a UNIFORM camera-clock grid ---
    dt = float(np.median(np.diff(tc)))           # ~16.67 ms
    g = np.arange(tc[0], tc[-1], dt)
    xi, yi = np.interp(g, tc, x), np.interp(g, tc, y)
    win = max(sg_poly + 2, int(round(sg_win_ms / 1e3 / dt)) | 1)   # odd
    vgx = savgol_filter(xi, win, sg_poly, deriv=1, delta=dt)
    vgy = savgol_filter(yi, win, sg_poly, deriv=1, delta=dt)
    vgx_q, vgy_q = np.interp(q, g, vgx), np.interp(q, g, vgy)
    df["vtan_sg"] = full(vgx_q * cos_h + vgy_q * sin_h)   # SSL tangential, SG
    return df, dict(dt_ms=dt * 1e3, sg_win=win)


def make_plot(session, robot, det, df, meta, fit, out, center_mode="setpoint"):
    t0 = df["t_robot"].iloc[0]
    rel = df["t_robot"].to_numpy() - t0
    enc = (robot["wheel0_speed"].to_numpy() + robot["wheel1_speed"].to_numpy()) / 2
    sp = (robot["wheel0_setpoint"].to_numpy() + robot["wheel1_setpoint"].to_numpy()) / 2

    # raw (unfiltered) camera tangential velocity: central diff of raw positions
    tc = det["t_capture"].to_numpy()
    keep = np.concatenate(([True], np.diff(tc) > 0))   # strictly increasing
    tc, xr, yr, thr = (tc[keep], det["x"].to_numpy()[keep] / 1000,
                       det["y"].to_numpy()[keep] / 1000, det["orientation"].to_numpy()[keep])
    vtan_raw = (np.gradient(xr, tc) * np.cos(thr) + np.gradient(yr, tc) * np.sin(thr))
    rel_cam = (tc - fit["b"]) / fit["a"] - t0

    # choose the zoom window
    if center_mode == "spike":  # worst spline-vs-SG disagreement = biggest outlier
        resid = np.abs(df["v_tangent"].to_numpy() - df["vtan_sg"].to_numpy())
        ctr_i, half = int(np.nanargmax(resid)), 2.0
    else:                        # largest setpoint step (a likely slip moment)
        ctr_i, half = int(np.nanargmax(np.abs(np.diff(sp)))), 4.0
    ctr = rel[ctr_i]
    lo, hi = max(0, ctr - half), min(rel[-1], ctr + half)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 7))
    ax1.plot(rel, df["v_tangent"], lw=0.8, label="camera v_tangent (spline)")
    ax1.axhline(0, color="k", lw=0.5)
    ax1.axvspan(lo, hi, color="orange", alpha=0.15, label="zoom window")
    ax1.set_title(f"Full session camera tangential speed (signed)  ({session})")
    ax1.set_ylabel("v_tangent [m/s]"); ax1.grid(alpha=0.3); ax1.legend(loc="upper right")

    m = (rel >= lo) & (rel <= hi)
    mc = (rel_cam >= lo) & (rel_cam <= hi)
    ax2.plot(rel_cam[mc], vtan_raw[mc], lw=0.7, alpha=0.45, color="red",
             label="camera v_tangent (raw central-diff)")
    ax2.plot(rel[m], df["v_tangent"].to_numpy()[m], lw=2.0, label="camera v_tangent (spline)")
    ax2.plot(rel[m], df["vtan_sg"].to_numpy()[m], lw=1.3, ls="--",
             label=f"camera v_tangent (Sav-Gol, {meta['sg_win']}-pt)")
    ax2.plot(rel[m], enc[m], lw=1.0, alpha=0.7, color="green",
             label="encoder body speed (ref)")
    ax2.plot(rel[m], sp[m], lw=1.0, alpha=0.5, color="gray", ls=":",
             label="setpoint (ref)")
    ax2.axhline(0, color="k", lw=0.5)
    ax2.set_title("Zoom: spline vs Savitzky-Golay tangential speed  (encoder/setpoint for context)")
    ax2.set_xlabel("time since session start [s], robot clock")
    ax2.set_ylabel("v_tangent [m/s]"); ax2.grid(alpha=0.3); ax2.legend(loc="upper right", ncol=2)

    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)
    print(f"saved plot -> {out}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--session", default="17:59")
    ap.add_argument("--lam", type=float, default=None, help="spline smoothing (default: GCV auto)")
    ap.add_argument("--zoom", choices=["setpoint", "spike"], default="setpoint",
                    help="zoom window: largest setpoint step, or biggest outlier")
    args = ap.parse_args()

    lam = args.lam if args.lam is not None else (
        float(os.getenv("ANALYSIS_SPLINE_LAM")) if os.getenv("ANALYSIS_SPLINE_LAM") else None)
    sg_win_ms = float(os.getenv("ANALYSIS_SG_WINDOW_MS", "120"))
    sg_poly = int(os.getenv("ANALYSIS_SG_POLYORDER", "3"))
    gap_max_ms = float(os.getenv("ANALYSIS_GAP_MAX_MS", "100"))

    engine = C.make_engine()
    session = C.resolve_session(engine, args.session)
    robot = C.load_robot(engine, session, cols=ROBOT_COLS)
    t0, t1 = robot["rx_wall"].min(), robot["rx_wall"].max()
    ball = C.load_ball(engine, t0, t1)
    det = C.load_detection(engine, t0, t1)
    print(f"session {session}: {len(robot)} robot, {len(det)} detections, {len(ball)} ball")

    fit = C.fit_timesync(robot, ball)
    print(f"time-sync: a={fit['a']:.9f}  residual σ={fit['resid_ms']:.1f} ms")

    df, meta = resample(robot, det, fit, lam, sg_win_ms, sg_poly, gap_max_ms)
    valid = df["covered"]
    masked = int((df["in_range"] & ~df["covered"]).sum())
    diff = (df["v_tangent"] - df["vtan_sg"])[valid]
    print("\n=== resample summary ===")
    print(f"  grid points          : {len(df)}")
    print(f"  within camera span    : {100*df['in_range'].mean():.1f}%")
    print(f"  covered (gap<={gap_max_ms:.0f}ms)  : {100*valid.mean():.1f}%   "
          f"(masked {masked} samples inside gaps)")
    print(f"  camera period         : {meta['dt_ms']:.2f} ms   SG window: {meta['sg_win']} pts")
    print(f"  spline λ              : {'GCV auto' if lam is None else lam}")
    print(f"  v_tangent min/med/max : {df['v_tangent'][valid].min():+.3f} / "
          f"{df['v_tangent'][valid].median():+.3f} / {df['v_tangent'][valid].max():+.3f} m/s")
    print(f"  v_normal  |median|    : {df['v_normal'][valid].abs().median():.3f} m/s (skid)")
    print(f"  |v_angular| med/max   : {df['v_angular'][valid].abs().median():.3f} / {df['v_angular'][valid].abs().max():.3f} rad/s")
    print(f"  spline vs SG v_tangent: RMS diff {np.sqrt((diff**2).mean()):.4f} m/s")

    tag = str(session).replace(" ", "_").replace(":", "")
    C.DERIVED.mkdir(parents=True, exist_ok=True)
    outp = C.DERIVED / f"resampled_{tag}.parquet"
    df.to_parquet(outp, index=False)
    print(f"saved data -> {outp}")
    make_plot(session, robot, det, df, meta, fit,
              C.FIGDIR / f"stage2_resample_{tag}_{args.zoom}.png", center_mode=args.zoom)


if __name__ == "__main__":
    main()
