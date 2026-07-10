#!/usr/bin/env python3
"""Final test — the one-shot honest evaluation on the reserved holdout.

For every model: refit on ALL development data (first 80% of each session) and
score ONCE on the untouched last-20%-per-session. This is the only place the
holdout is read; run it after model selection / tuning is locked. Tabular models
give a single holdout number; the ESN is averaged over its reservoir seeds.

Run:  .venv/bin/python analysis/slip_final_test.py
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


def main():
    argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    ex = D.load_examples()
    dev = ex[ex["split"] == "dev"]
    test = ex[ex["split"] == "test"]
    print(f"dev examples: {len(dev)}   holdout examples: {len(test)}  "
          f"({test['session'].nunique()} sessions)\n")

    rows = {}   # name -> (mae, rmse, f1)
    for m in M.TABULAR:
        rows[m.NAME] = H.fit_predict_tabular(m.factory, dev, test)
    for m in M.SEQUENCE:
        dev_seqs, test_seqs = D.esn_sequences("dev"), D.esn_sequences("test")
        r = m.final_test(dev_seqs, test_seqs)      # (n_seed, 3)
        rows[m.NAME] = tuple(r.mean(0))
        print(f"{m.NAME}: averaged over {len(r)} reservoir seeds "
              f"(MAE seed-std {r[:, 0].std():.4f})")

    print(f"\n{'model':14} {'MAE [m/s]':>12} {'RMSE [m/s]':>12} {'detect F1':>12}")
    for name, (mae, rmse, f1) in rows.items():
        print(f"{name:14} {mae:12.4f} {rmse:12.4f} {f1:12.3f}")

    import json
    (C.DERIVED / "final_test.json").write_text(json.dumps(
        {n: {"mae": m, "rmse": r, "f1": f} for n, (m, r, f) in rows.items()}, indent=2))

    names = list(rows)
    neural = {"MLP", "ESN"}          # colour by model family (classic vs neural)
    colors = ["tab:red" if n in neural else "tab:blue" for n in names]
    x = np.arange(len(names))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5))
    a1.bar(x, [rows[n][0] for n in names], color=colors)
    a1.set_ylabel("MAE [m/s]"); a1.set_title("Final-test MAE (lower better)")
    a2.bar(x, [rows[n][2] for n in names], color=colors)
    a2.set_ylabel("detection F1"); a2.set_title("Final-test slip-detection F1")
    for a in (a1, a2):
        a.set_xticks(x); a.set_xticklabels(names, rotation=20); a.grid(alpha=.3, axis="y")
    fig.suptitle("Slip-velocity models — reserved last-20% final test "
                 "(blue=classic, red=neural)", fontweight="bold")
    fig.tight_layout()
    out = C.FIGDIR / "slip_final_test.png"
    fig.savefig(out, dpi=120)
    print(f"\nsaved plot -> {out}")


if __name__ == "__main__":
    main()
