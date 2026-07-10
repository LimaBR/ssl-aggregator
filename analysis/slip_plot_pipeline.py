#!/usr/bin/env python3
"""Draw the end-to-end processing pipeline, from data capture to slip models.

Three phases: (1) Capture — robot + SSL-Vision telemetry logged to PostgreSQL by
the Phase-1 C++ loggers; (2) Labeling — Stages 1-4 turn raw data into per-wheel
slip labels; (3) Modeling — Stage 5 features, split, tuning, comparison, final
test, and ExecuTorch export. This is a schematic (no data is read).

Run:  .venv/bin/python analysis/slip_plot_pipeline.py
"""
from __future__ import annotations

import argparse

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle, Patch

import common as C

CAP, LAB, MOD = "#cfe8f5", "#d6efd6", "#f7d9d5"      # box fills per phase
ART = "#ffe0a3"                                       # data-artifact fill
BG = {"cap": "#eef6fc", "lab": "#eff8ef", "mod": "#fdeeec"}


def box(ax, cx, cy, w, h, title, sub, fc, ec="#333"):
    ax.add_patch(FancyBboxPatch(
        (cx - w / 2, cy - h / 2), w, h,
        boxstyle="round,pad=0.1,rounding_size=1.1",
        linewidth=1.3, edgecolor=ec, facecolor=fc, zorder=4))
    ax.text(cx, cy + h * 0.17, title, ha="center", va="center",
            fontsize=12.5, fontweight="bold", zorder=5)
    ax.text(cx, cy - h * 0.26, sub, ha="center", va="center",
            fontsize=9, color="#333", zorder=5)
    return dict(top=(cx, cy + h / 2), bot=(cx, cy - h / 2),
                left=(cx - w / 2, cy), right=(cx + w / 2, cy), cx=cx, cy=cy)


def arrow(ax, a, b, ls="-", color="#555", text=None, rad=0.0):
    ax.add_patch(FancyArrowPatch(
        a, b, arrowstyle="-|>", mutation_scale=17, lw=1.7, color=color,
        linestyle=ls, shrinkA=3, shrinkB=3, zorder=3,
        connectionstyle=f"arc3,rad={rad}"))
    if text:
        ax.text((a[0] + b[0]) / 2 + 1.5, (a[1] + b[1]) / 2, text,
                fontsize=9, color=color, style="italic", ha="left", va="center")


def band(ax, y0, y1, color, label):
    ax.add_patch(Rectangle((2.5, y0), 95, y1 - y0, facecolor=color, edgecolor="none",
                           zorder=0))
    ax.text(4.3, (y0 + y1) / 2, label, rotation=90, va="center", ha="center",
            fontsize=13.5, fontweight="bold", color="#555", zorder=1)


def main():
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()

    fig = plt.figure(figsize=(13, 15))
    ax = fig.add_axes([0.006, 0.005, 0.988, 0.99])
    ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.axis("off")

    ax.text(51, 98.7, "Wheel-slip system — end-to-end processing pipeline",
            ha="center", va="center", fontsize=17, fontweight="bold")
    band(ax, 71.25, 97.3, BG["cap"], "CAPTURE  (Phase 1)")
    band(ax, 29.75, 71.25, BG["lab"], "LABELING  (Stages 1–4)")
    band(ax, 0, 29.75, BG["mod"], "MODELING  (Stage 5)")

    # grid: shared left/right margins (9 / 91); boxes span 1, 2 or 3 columns
    WF = 82                       # full width (1 column)
    W2, C2L, C2R = 39, 28.5, 71.5                    # 2 across
    W3, C3 = 24.667, (21.333, 50, 78.667)            # 3 across

    # ---- capture -------------------------------------------------------------
    robot = box(ax, C2L, 91, W2, 7.4, "Robot  (differential drive)",
                "wheel encoders · IMU · orange LED · UDP @100 Hz", CAP)
    cam = box(ax, C2R, 91, W2, 7.4, "SSL-Vision camera  @60 Hz",
              "robot pose (x, y, θ) · ball = LED blob · UDP", CAP)
    ax.annotate("", (52, 91), (48, 91),
                arrowprops=dict(arrowstyle="<|-|>", color="#c47f17", lw=1.6))
    ax.text(50, 95.8, "orange LED ⇄ ball  ·  shared time-sync channel", fontsize=9,
            style="italic", ha="center", va="center", color="#c47f17")
    tlog = box(ax, C2L, 82.5, W2, 6.6, "C++ telemetry logger",
               "→ robot.telemetry  (+ rx_wall)", CAP)
    vlog = box(ax, C2R, 82.5, W2, 6.6, "C++ vision logger",
               "→ vision.robot_detection / ball_detection", CAP)
    pg = box(ax, 50, 74.5, WF, 6.6, "PostgreSQL  (robot_data)",
             "robot.telemetry · vision.robot_detection · vision.ball_detection", CAP)
    arrow(ax, robot["bot"], tlog["top"]); arrow(ax, cam["bot"], vlog["top"])
    arrow(ax, tlog["bot"], (43, 77.8)); arrow(ax, vlog["bot"], (57, 77.8))

    # ---- labeling ------------------------------------------------------------
    s1 = box(ax, 50, 66.5, WF, 6.4, "Stage 1 — time sync",
             "fit  t_capture ≈ a·(packet_id·0.01) + b  from LED / ball edges", LAB)
    s2 = box(ax, 50, 58.5, WF, 6.4, "Stage 2 — resample to 100 Hz",
             "smoothing spline → pose, v, ω  ·  camera gaps >100 ms masked", LAB)
    s3 = box(ax, 50, 50.5, WF, 6.4, "Stage 3 — inverse kinematics",
             "camera body motion → per-wheel ground speed  (v_tangent ∓ ω·track/2)", LAB)
    s4 = box(ax, 50, 42.5, WF, 6.4, "Stage 4 — slip labels",
             "slip_vel = v_encoder − v_ground   ·   clean_telemetry (outliers)", LAB)
    pq = box(ax, 50, 34.5, WF, 6.6, "derived/slip_labels.parquet",
             "≈198 k rows · telemetry + per-wheel slip_vel + coverage masks", ART)
    arrow(ax, pg["bot"], s1["top"])
    for a, b in [(s1, s2), (s2, s3), (s3, s4), (s4, pq)]:
        arrow(ax, a["bot"], b["top"])

    # ---- modeling ------------------------------------------------------------
    data = box(ax, 50, 26, WF, 6.6, "slip_data  +  slip_harness",
               "causal 200 ms window features (tabular) + raw sequences (ESN) · "
               "LOSO + metrics", MOD)
    reg = box(ax, C2L, 17, W2, 6.8, "model cards + registry",
              "kNN · RandomForest · XGBoost · MLP · ESN", MOD)
    exp = box(ax, C2R, 17, W2, 6.8, "ExecuTorch export",
              "torch.export → .pte → Raspberry Pi", MOD)
    tune = box(ax, C3[0], 8, W3, 6.8, "slip_tune",
               "Optuna TPE + pruner (dev LOSO)", MOD)
    comp = box(ax, C3[1], 8, W3, 6.8, "slip_compare",
               "LOSO table (dev)", MOD)
    fin = box(ax, C3[2], 8, W3, 6.8, "slip_final_test",
              "one-shot on 20% holdout", MOD)
    arrow(ax, pq["bot"], data["top"])
    arrow(ax, data["bot"], reg["top"]); arrow(ax, reg["right"], exp["left"])
    for d in (tune, comp, fin):
        arrow(ax, reg["bot"], d["top"])
    arrow(ax, (24, tune["top"][1]), (32, reg["bot"][1]),
          ls="--", color="#b5651d", rad=-0.3, text="best_hparams.json")

    ax.legend(handles=[Patch(color=CAP, label="capture / storage"),
                       Patch(color=LAB, label="labeling stage"),
                       Patch(color=MOD, label="modeling step"),
                       Patch(color=ART, label="data artifact")],
              loc="lower center", bbox_to_anchor=(0.52, 0.002), ncol=4, fontsize=11,
              frameon=False)
    out = C.FIGDIR / "slip_pipeline.png"
    fig.savefig(out, dpi=120)
    print(f"saved plot -> {out}")


if __name__ == "__main__":
    main()
