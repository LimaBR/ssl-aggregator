#!/usr/bin/env python3
"""Plot predicted vs actual slip over time on the reserved holdout (final test).

Refits one model on ALL development data, predicts on a chosen session's last-20%
holdout, and plots a 2x2 grid: rows = wheels (left/right), columns = full holdout
vs a zoomed window. Each panel shows ground-truth slip velocity, the model's
prediction, the ±0.20 m/s detection band, the actual slip intervals (shaded), and
the P/R/F1 over that panel's visible window. This is the time-domain view behind
the detection-F1 number.

Run:  .venv/bin/python analysis/slip_plot_test.py [--model mlp] [--session 22:52]
                                                  [--zoom 0 45]
"""
from __future__ import annotations

import argparse

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import common as C
import slip_data as D
import slip_models as M

CARD = {m.NAME.lower(): m for m in M.TABULAR}   # tabular cards are plottable per-row


def break_gaps(t, series, max_gap=0.05):
    """Insert NaNs across camera/coverage gaps so lines don't bridge them."""
    brk = np.diff(t, prepend=t[0]) > max_gap
    s = series.astype(float).copy()
    s[brk] = np.nan
    return s


def auto_zoom(t, ev, width):
    """Pick the [lo, lo+width] window containing the most slip events."""
    if not ev.any():
        return float(t[0]), float(t[0] + width)
    starts = t[ev]
    best_lo, best_n = starts[0], -1
    for lo in starts:
        n = int(((t >= lo) & (t <= lo + width) & ev).sum())
        if n > best_n:
            best_lo, best_n = lo, n
    return float(best_lo), float(best_lo + width)


def draw(ax, t, yt, yp, side, window=None, mark_span=None):
    ev_true = np.abs(yt) > D.SLIP_FLAG
    ev_pred = np.abs(yp) > D.SLIP_FLAG
    ax.fill_between(t, -1, 1, where=ev_true, color="tab:orange", alpha=0.15, step="mid",
                    transform=ax.get_xaxis_transform(), label="actual slip event")
    ax.plot(t, break_gaps(t, yt), color="black", lw=0.9, alpha=0.7, label="ground truth")
    ax.plot(t, break_gaps(t, yp), color="tab:red", lw=0.9, label="predicted")
    for s in (D.SLIP_FLAG, -D.SLIP_FLAG):
        ax.axhline(s, color="gray", ls="--", lw=0.8)
    if mark_span is not None:
        ax.axvspan(*mark_span, color="tab:blue", alpha=0.08, zorder=0)

    sel = np.ones(len(t), bool) if window is None else (t >= window[0]) & (t <= window[1])
    if window is not None:
        ax.set_xlim(*window)
    et, ep = ev_true[sel], ev_pred[sel]
    tp = int((et & ep).sum()); fp = int((~et & ep).sum()); fn = int((et & ~ep).sum())
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    scope = "full" if window is None else f"{window[0]:.0f}-{window[1]:.0f}s"
    ax.set_title(f"{side} wheel [{scope}]   P {prec:.2f}  R {rec:.2f}  F1 {f1:.2f}",
                 fontsize=10, loc="left")
    ax.grid(alpha=0.3)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", default="mlp", choices=sorted(CARD),
                    help="tabular model to fit (default: mlp)")
    ap.add_argument("--session", default=None,
                    help="session substring; default = holdout with most slip")
    ap.add_argument("--zoom", type=float, nargs=2, metavar=("LO", "HI"), default=None,
                    help="zoom window [s] within the holdout; default = auto (densest slip)")
    ap.add_argument("--zoom-width", type=float, default=15.0,
                    help="width [s] of the auto zoom window (default: 15)")
    ap.add_argument("--zoom-only", action="store_true",
                    help="render only the zoom column (left+right wheel), wide layout")
    args = ap.parse_args()

    ex = D.load_examples()
    dev = ex[ex["split"] == "dev"]
    test = ex[ex["split"] == "test"]

    if args.session:
        sess = [s for s in test["session"].unique() if args.session in str(s)]
        if len(sess) != 1:
            raise SystemExit(f"--session '{args.session}' matched {len(sess)} sessions")
        session = sess[0]
    else:
        ev = test.assign(slip=test["y"].abs() > D.SLIP_FLAG).groupby("session")["slip"].sum()
        session = ev.idxmax()

    model = CARD[args.model].factory()
    model.fit(dev[D.FEATURES].to_numpy(), dev["y"].to_numpy())

    # per-side time / truth / prediction on this session's holdout
    per_side = {}
    for side in ("left", "right"):
        d = test[(test["session"] == session) & (test["side"] == side)].sort_values("packet_id")
        t = d["packet_id"].to_numpy() * C.PACKET_DT
        per_side[side] = (t - t[0], d["y"].to_numpy(), model.predict(d[D.FEATURES].to_numpy()))

    # zoom window: explicit, else auto from combined events of both wheels
    if args.zoom:
        window = (float(args.zoom[0]), float(args.zoom[1]))
    else:
        tl, ytl, _ = per_side["left"]
        _, ytr, _ = per_side["right"]
        ev = (np.abs(ytl) > D.SLIP_FLAG) | (np.abs(ytr) > D.SLIP_FLAG)
        window = auto_zoom(tl, ev, args.zoom_width)
    print(f"model={args.model}  session={session}  zoom={window[0]:.0f}-{window[1]:.0f}s")

    if args.zoom_only:
        fig, axes = plt.subplots(2, 1, figsize=(12, 5.2), sharex=True)
        for row, side in enumerate(("left", "right")):
            t, yt, yp = per_side[side]
            draw(axes[row], t, yt, yp, side, window=window)
            axes[row].set_ylabel("slip velocity [m/s]")
        axes[0].legend(loc="upper right", ncol=3, fontsize=8)
        axes[1].set_xlabel("time within holdout [s]  (zoom)")
        fig.suptitle(f"Holdout slip — predicted vs actual (zoom {window[0]:.0f}"
                     f"–{window[1]:.0f} s)   ({session}, {args.model.upper()})",
                     fontweight="bold")
        fig.tight_layout()
        out = C.FIGDIR / f"slip_test_timeseries_{args.model}_zoom.png"
        fig.savefig(out, dpi=120)
        print(f"saved plot -> {out}")
        return

    fig, axes = plt.subplots(2, 2, figsize=(15, 7.5),
                             gridspec_kw={"width_ratios": [2, 1]})
    for row, side in enumerate(("left", "right")):
        t, yt, yp = per_side[side]
        draw(axes[row, 0], t, yt, yp, side, window=None, mark_span=window)  # full
        draw(axes[row, 1], t, yt, yp, side, window=window)                   # zoom
        axes[row, 0].set_ylabel("slip velocity [m/s]")
    axes[0, 0].legend(loc="upper right", ncol=3, fontsize=8)
    axes[1, 0].set_xlabel("time within holdout [s]")
    axes[1, 1].set_xlabel("time within holdout [s]  (zoom)")
    fig.suptitle(f"Holdout slip — predicted vs actual   ({session}, {args.model.upper()})",
                 fontweight="bold")
    fig.tight_layout()
    out = C.FIGDIR / f"slip_test_timeseries_{args.model}.png"
    fig.savefig(out, dpi=120)
    print(f"saved plot -> {out}")


if __name__ == "__main__":
    main()
