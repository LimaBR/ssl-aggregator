#!/usr/bin/env python3
"""Compare all slip models by leave-one-session-out on the development set.

Iterates the model registry, runs each through the appropriate LOSO evaluator,
prints a MAE / RMSE / detection-F1 table, saves a bar chart, and smoke-tests
torch.export on the two neural models (ExecuTorch-readiness). The reserved
last-20%-per-session final test is NOT touched here — see slip_final_test.py.

Run:  .venv/bin/python analysis/slip_compare.py
"""
from __future__ import annotations

import argparse

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import common as C
import slip_data as D
import slip_harness as H
import slip_models as M


def check_export():
    """Trace exportable cards with torch.export — the front half of ExecuTorch."""
    from torch.export import export
    print("\ntorch.export (ExecuTorch-readiness):")
    for m in M.ALL:
        if not hasattr(m, "export_example"):
            continue
        mod, args = m.export_example()
        try:
            export(mod, args)
            print(f"  {m.NAME:12}: OK  (traces to an exportable graph)")
        except Exception as e:                       # noqa: BLE001
            print(f"  {m.NAME:12}: FAILED — {type(e).__name__}: {e}")


def main():
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    ex = D.load_examples()
    dev = ex[ex["split"] == "dev"]
    print(f"dev examples: {len(dev)}  ({dev['session'].nunique()} sessions)\n")

    results = {}
    for m in M.TABULAR:
        results[m.NAME] = H.evaluate(m.factory, dev)
    for m in M.SEQUENCE:
        print(f"running {m.NAME} (sequence, {len(m.SEEDS)} reservoir seeds) ...")
        results[m.NAME] = m.evaluate()

    print(f"\n{'model':14} {'MAE [m/s]':>16} {'RMSE [m/s]':>16} {'detect F1':>16}")
    for name, r in results.items():
        mean, std = r.mean(0), r.std(0)
        print(f"{name:14} {mean[0]:7.4f} ± {std[0]:.4f}   "
              f"{mean[1]:7.4f} ± {std[1]:.4f}   {mean[2]:6.3f} ± {std[2]:.3f}")

    names = list(results)
    neural = {"MLP", "ESN"}          # colour by model family (classic vs neural)
    colors = ["tab:red" if n in neural else "tab:blue" for n in names]
    x = np.arange(len(names))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5))
    a1.bar(x, [results[n][:, 0].mean() for n in names],
           yerr=[results[n][:, 0].std() for n in names], capsize=4, color=colors)
    a1.set_ylabel("MAE [m/s]"); a1.set_title("MAE (lower better)")
    a2.bar(x, [results[n][:, 2].mean() for n in names],
           yerr=[results[n][:, 2].std() for n in names], capsize=4, color=colors)
    a2.set_ylabel("detection F1"); a2.set_title("Slip-detection F1 (higher better)")
    for a in (a1, a2):
        a.set_xticks(x); a.set_xticklabels(names, rotation=20); a.grid(alpha=.3, axis="y")
    fig.suptitle("Slip-velocity models — LOSO on dev  (blue=classic, red=neural)",
                 fontweight="bold")
    fig.tight_layout()
    out = C.FIGDIR / "slip_compare.png"
    fig.savefig(out, dpi=120)
    print(f"\nsaved plot -> {out}")

    check_export()


if __name__ == "__main__":
    main()
