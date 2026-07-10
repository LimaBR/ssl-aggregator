#!/usr/bin/env python3
"""Visualise the Optuna hyperparameter search for every tuned model.

Reads the per-trial logs written by slip_tune.py (derived/tune_trials_*.csv) and
draws one column per model: the optimisation history (each trial's LOSO MAE + the
best-so-far curve, pruned trials marked) and slice scatters of the objective
against that model's most influential hyperparameters, coloured by search
progression, with the selected optimum starred. A single y-axis (LOSO MAE) and a
dotted overall-best line are shared across every panel so heights are directly
comparable between models.

Run:  .venv/bin/python analysis/slip_plot_tune.py     (needs slip_tune.py first)
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import common as C

# column order and per-model slice specs: (param, log-x, categorical?)
MODELS = [("kNN", "knn"), ("RandomForest", "rf"), ("XGBoost", "xgb"),
          ("MLP", "mlp"), ("ESN", "esn")]
SLICES = {
    "knn": [("n_neighbors", False, False), ("weights", False, True), ("p", False, True)],
    "rf":  [("n_estimators", False, False), ("max_depth", False, False),
            ("min_samples_leaf", False, False), ("max_features", False, False)],
    "xgb": [("learning_rate", True, False), ("max_depth", False, False),
            ("n_estimators", False, False), ("reg_lambda", True, False)],
    "mlp": [("lr", True, False), ("huber_delta", True, False),
            ("epochs", False, False), ("weight_decay", True, False)],
    "esn": [("sr", False, False), ("leak", False, False),
            ("in_scale", True, False), ("ridge", True, False)],
}
COLORS = {"knn": "tab:blue", "rf": "tab:green", "xgb": "tab:cyan",
          "mlp": "tab:red", "esn": "tab:purple"}
_RNG = np.random.default_rng(0)


def convergence(ax, df, name, key, top):
    comp = df[df["state"] == "COMPLETE"].sort_values("number")
    pruned = df[df["state"] == "PRUNED"]
    best = np.minimum.accumulate(comp["value"].to_numpy())
    ax.scatter(comp["number"], comp["value"], s=15, color=COLORS[key], alpha=0.5)
    ax.plot(comp["number"], best, color="black", lw=1.6, label="best so far")
    if len(pruned):
        ax.scatter(pruned["number"], np.full(len(pruned), top), marker="x", s=16,
                   color="gray", alpha=0.6, label=f"pruned ({len(pruned)})")
    imin = comp["value"].idxmin()
    bx, by = comp.loc[imin, "number"], comp.loc[imin, "value"]
    ax.scatter(bx, by, marker="*", s=190, color="gold", edgecolor="black", zorder=6)
    ax.annotate(f"{by:.4f}", (bx, by), textcoords="offset points", xytext=(3, 8),
                fontsize=8, fontweight="bold")
    ax.set_title(name, fontsize=12, fontweight="bold")
    ax.set_xlabel("trial", fontsize=8.5)
    ax.grid(alpha=0.3); ax.legend(fontsize=6.5, loc="upper right")


def slice_panel(ax, df, name, spec):
    param, logx, cat = spec
    comp = df[df["state"] == "COMPLETE"]
    y = comp["value"].to_numpy()
    frac = comp["number"].to_numpy() / max(comp["number"].max(), 1)
    xraw = comp[f"params_{param}"].to_numpy()
    if cat or xraw.dtype == object:
        cats = sorted(pd.unique(xraw), key=str)
        pos = {v: i for i, v in enumerate(cats)}
        x = np.array([pos[v] for v in xraw], float) + (_RNG.random(len(xraw)) - 0.5) * 0.18
        ax.set_xticks(range(len(cats))); ax.set_xticklabels([str(c) for c in cats])
    else:
        x = xraw.astype(float)
        if logx:
            ax.set_xscale("log")
    sc = ax.scatter(x, y, c=frac, cmap="viridis", vmin=0, vmax=1, s=24, edgecolor="none")
    ib = int(np.argmin(y))
    ax.scatter(x[ib], y[ib], marker="*", s=190, color="gold", edgecolor="black", zorder=6)
    ax.set_xlabel(f"{name} · {param}", fontsize=8.5)
    ax.grid(alpha=0.3)
    return sc


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--history-only", action="store_true",
                    help="apenas a linha de histórico (trial × LOSO MAE) dos 5 modelos")
    args = ap.parse_args()

    frames = {}
    for _, key in MODELS:
        path = C.DERIVED / f"tune_trials_{key}.csv"
        if not path.exists():
            raise SystemExit(f"missing {path} — run slip_tune.py first")
        frames[key] = pd.read_csv(path)

    comp_all = np.concatenate([frames[k].loc[frames[k]["state"] == "COMPLETE", "value"]
                               .to_numpy() for _, k in MODELS])
    lo, hi, gbest = comp_all.min() * 0.97, comp_all.max() * 1.03, comp_all.min()

    if args.history_only:
        fig, axes = plt.subplots(1, len(MODELS), figsize=(18, 4.6), layout="constrained")
        for col, (name, key) in enumerate(MODELS):
            convergence(axes[col], frames[key], name, key, top=hi * 0.98)
            axes[col].set_ylim(lo, hi)
            axes[col].axhline(gbest, color="gray", ls=":", lw=1.0, zorder=1)
            if col:
                axes[col].set_ylabel("")
        axes[0].text(axes[0].get_xlim()[1], gbest, f" best {gbest:.4f}",
                     fontsize=7.5, color="gray", va="bottom", ha="right")
        fig.suptitle("Otimização — histórico (trial × LOSO MAE)  ·  Optuna TPE + "
                     "median pruner  ·  ★ = selecionado; pontilhado = melhor global",
                     fontweight="bold", fontsize=13)
        out = C.FIGDIR / "slip_tune_history.png"
        fig.savefig(out, dpi=120)
        print(f"saved plot -> {out}")
        return

    nrows = 1 + max(len(SLICES[k]) for _, k in MODELS)
    fig, axes = plt.subplots(nrows, len(MODELS), figsize=(19, 14), layout="constrained")
    last_sc = None
    for col, (name, key) in enumerate(MODELS):
        df = frames[key]
        convergence(axes[0, col], df, name, key, top=hi * 0.98)
        specs = SLICES[key]
        for r in range(1, nrows):
            if r - 1 < len(specs):
                last_sc = slice_panel(axes[r, col], df, name, specs[r - 1])
            else:
                axes[r, col].axis("off")

    for a in axes.ravel():
        if a.has_data():
            a.set_ylim(lo, hi)
            a.axhline(gbest, color="gray", ls=":", lw=1.0, zorder=1)
    for r in range(nrows):                       # LOSO-MAE label on the left column
        axes[r, 0].set_ylabel("LOSO MAE [m/s]")
    axes[0, 0].text(axes[0, 0].get_xlim()[1], gbest, f" best {gbest:.4f}",
                    fontsize=7.5, color="gray", va="bottom", ha="right")

    cbar = fig.colorbar(last_sc, ax=axes[1:, :].ravel().tolist(), shrink=0.55,
                        pad=0.015, location="right")
    cbar.set_label("search progression (0 = first trial → 1 = last)")
    fig.suptitle("Hyperparameter tuning — all models  (Optuna TPE + median pruner; "
                 "objective = dev LOSO MAE; ★ = selected; dotted = overall best)",
                 fontweight="bold", fontsize=13)
    out = C.FIGDIR / "slip_tune_detail.png"
    fig.savefig(out, dpi=120)
    print(f"saved plot -> {out}")


if __name__ == "__main__":
    main()
