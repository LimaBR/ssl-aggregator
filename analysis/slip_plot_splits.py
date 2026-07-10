#!/usr/bin/env python3
"""Illustrate the train / validation / holdout split strategy.

Top panel: each session's real timeline, cut at 80% into the development set and
the reserved last-20% final-test holdout. Bottom panel: the leave-one-session-out
(LOSO) rotation used for validation — one session validates while the others
train — with the 20% holdout of every session carved off in every fold and never
touched until the final test.

Run:  .venv/bin/python analysis/slip_plot_splits.py
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Patch

import common as C
import slip_data as D

DEV_C, HOLD_C, VAL_C = "tab:blue", "tab:orange", "tab:purple"


def session_spans():
    """Per session: (label, dev_seconds, holdout_seconds, n_dev, n_hold)."""
    df = pd.read_parquet(C.DERIVED / "slip_labels.parquet")
    rows = []
    for ses, g in df.groupby("capture_session"):
        pid = g["packet_id"].to_numpy()
        cut = np.quantile(pid, D.DEV_FRAC)
        dev = pid <= cut
        dur = (pid.max() - pid.min()) * C.PACKET_DT
        dev_s = (cut - pid.min()) * C.PACKET_DT
        label = pd.Timestamp(ses).strftime("%H:%M:%S")
        rows.append((label, dev_s, dur - dev_s, int(dev.sum()), int((~dev).sum())))
    return rows


def main():
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    spans = session_spans()
    n = len(spans)

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8),
                                   gridspec_kw={"height_ratios": [1, 1.1]})

    # ---- panel 1: real per-session timeline, 80/20 temporal cut ---------------
    for i, (label, dev_s, hold_s, n_dev, n_hold) in enumerate(spans):
        y = n - 1 - i
        ax1.barh(y, dev_s, color=DEV_C, edgecolor="white")
        ax1.barh(y, hold_s, left=dev_s, color=HOLD_C, edgecolor="white")
        ax1.text(dev_s / 2, y, f"dev 80%\n{n_dev:,} rows", ha="center", va="center",
                 color="white", fontsize=8, fontweight="bold")
        ax1.text(dev_s + hold_s / 2, y, f"holdout\n20%\n{n_hold:,}", ha="center",
                 va="center", color="white", fontsize=7, fontweight="bold")
    ax1.set_yticks(range(n))
    ax1.set_yticklabels([spans[n - 1 - i][0] for i in range(n)])
    ax1.set_xlabel("time within session [s]")
    ax1.set_ylabel("capture session")
    ax1.set_title("Per-session temporal split — first 80% develops, last 20% is the "
                  "reserved final-test holdout", fontsize=11, loc="left")
    ax1.set_ylim(-0.6, n - 0.4)

    # ---- panel 2: LOSO rotation on the dev portion ---------------------------
    labels = [s[0] for s in spans]
    pad, dev_frac = 0.08, 0.8
    for r in range(n):                       # fold r: session r validates
        for c in range(n):                   # column = session
            x0, y0 = c + pad, (n - 1 - r) + pad
            w, h = 1 - 2 * pad, 1 - 2 * pad
            role_c = VAL_C if c == r else DEV_C
            ax2.add_patch(Rectangle((x0, y0), w * dev_frac, h, color=role_c))
            ax2.add_patch(Rectangle((x0 + w * dev_frac, y0), w * (1 - dev_frac), h,
                                    color=HOLD_C))
            ax2.text(x0 + w * dev_frac / 2, y0 + h / 2,
                     "VAL" if c == r else "train", ha="center", va="center",
                     color="white", fontsize=8, fontweight="bold")
        ax2.text(-0.1, (n - 1 - r) + 0.5, f"Fold {r + 1}", ha="right", va="center",
                 fontsize=9)
    ax2.set_xlim(-0.9, n)
    ax2.set_ylim(0, n)
    ax2.set_xticks([c + 0.5 for c in range(n)])
    ax2.set_xticklabels(labels)
    ax2.set_yticks([])
    ax2.set_xlabel("capture session")
    ax2.set_title("LOSO validation on the development set — each session validates "
                  "once; holdout stays reserved every fold", fontsize=11, loc="left")
    ax2.legend(handles=[Patch(color=DEV_C, label="train (dev)"),
                        Patch(color=VAL_C, label="validation (dev)"),
                        Patch(color=HOLD_C, label="holdout (reserved)")],
               loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, fontsize=8)

    fig.suptitle("Slip models — data splitting: LOSO validation + reserved temporal "
                 "holdout", fontweight="bold")
    fig.tight_layout()
    out = C.FIGDIR / "slip_splits.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    print(f"saved plot -> {out}")


if __name__ == "__main__":
    main()
