#!/usr/bin/env python3
"""Stage 1 — robot <-> camera time synchronisation via the LED / ball channel.

Fits  t_capture ≈ a*(packet_id*0.01) + b  for one capture_session using the
LED (robot) and ball-presence (camera) square-wave edges, and saves an overlay
plot proving the alignment. Fit logic lives in common.py.

Run:  .venv/bin/python analysis/stage1_timesync.py [--session 17:59] [--list]
"""
from __future__ import annotations

import argparse

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import common as C


def presence_on_grid(grid_cam, intervals):
    pres = np.zeros(grid_cam.size, bool)
    for r, f in intervals:
        pres |= (grid_cam >= r) & (grid_cam <= f)
    return pres.astype(int)


def make_plot(session, fit, out):
    t_robot, led = fit["t_robot"], fit["led"]
    a, b = fit["a"], fit["b"]
    t0 = t_robot.min()
    rel = t_robot - t0
    grid = np.arange(t_robot.min(), t_robot.max(), 0.02)
    ball_pres = presence_on_grid(a * grid + b, fit["intervals"])

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 6.5))
    for ax, span, title in (
        (ax1, None, f"Full session  ({session})"),
        (ax2, (rel.max() / 2, rel.max() / 2 + 12), "12 s zoom"),
    ):
        ax.step(rel, led, where="post", lw=1.6, label="robot led_state")
        ax.step(grid - t0, ball_pres * 0.9, where="post", lw=1.6, ls="--",
                label="camera ball-presence (mapped)")
        ax.set_ylim(-0.15, 1.25); ax.set_ylabel("on / off")
        ax.set_title(title); ax.grid(alpha=0.3)
        if span:
            ax.set_xlim(*span)
    ax2.set_xlabel("time since session start [s], robot clock")
    ax1.legend(loc="upper right", ncol=2)
    fig.suptitle(f"Stage 1 time-sync — drift a={a:.9f}  residual σ={fit['resid_ms']:.1f} ms",
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
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    engine = C.make_engine()
    if args.list:
        print(C.list_sessions(engine).to_string(index=False))
        return

    session = C.resolve_session(engine, args.session)
    robot = C.load_robot(engine, session)
    ball = C.load_ball(engine, robot["rx_wall"].min(), robot["rx_wall"].max())
    print(f"session {session}: {len(robot)} robot rows, {len(ball)} ball rows")

    fit = C.fit_timesync(robot, ball)
    print("\n=== time-sync fit  t_capture = a*(packet_id*0.01) + b ===")
    print(f"  matched edges     : {fit['n']}  (kept {fit['kept']})")
    print(f"  drift  a          : {fit['a']:.9f}   ({fit['drift_ms']:+.1f} ms over {fit['duration']:.0f}s)")
    print(f"  offset b          : {fit['b']:.6f}  (epoch s)")
    print(f"  residual σ        : {fit['resid_ms']:.1f} ms   (sync quality)")
    print(f"  LED->camera lag   : {fit['latency_ms']:+.1f} ms")

    tag = str(session).replace(" ", "_").replace(":", "")
    make_plot(session, fit, C.FIGDIR / f"stage1_timesync_{tag}.png")


if __name__ == "__main__":
    main()
