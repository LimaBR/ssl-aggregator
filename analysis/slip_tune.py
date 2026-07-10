#!/usr/bin/env python3
"""Optuna hyperparameter search for every tunable model (registry-driven).

Each model card exposes a `search_space(trial)`; this driver runs a study per
card. Tabular cards (kNN / RandomForest / XGBoost / MLP) share the tabular LOSO
objective; the ESN uses the sequence objective and averages several reservoir
seeds. All searches optimise the LOSO-average MAE on the development set only
(the reserved holdout is never touched here), with TPE + a median pruner using
per-fold intermediate reporting. Best configs go to derived/best_hparams.json —
from where every model card picks them up automatically — per-trial logs to
derived/tune_trials_<key>.csv, and a convergence plot to figures/slip_tune.png.

Run:  .venv/bin/python analysis/slip_tune.py [--classic-trials 20] [--mlp-trials 40]
                                             [--esn-trials 30] [--esn-seeds 3]
"""
from __future__ import annotations

import argparse
import json
import time

import numpy as np
import pandas as pd
import optuna

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import common as C
import slip_data as D
import slip_harness as H
import slip_models as M

optuna.logging.set_verbosity(optuna.logging.WARNING)

COLORS = {"knn": "tab:blue", "rf": "tab:green", "xgb": "tab:cyan",
          "mlp": "tab:red", "esn": "tab:purple"}


def _prune(trial):
    def report(val, step):
        trial.report(val, step)
        if trial.should_prune():
            raise optuna.TrialPruned()
    return report


def make_tabular_objective(card, dev):
    def objective(trial):
        params = card.search_space(trial)
        r = H.evaluate(lambda: card.build(params), dev, report=_prune(trial)).mean(0)
        trial.set_user_attr("rmse", float(r[1]))
        trial.set_user_attr("f1", float(r[2]))
        return float(r[0])
    return objective


def make_esn_objective(card, seqs, sessions, seeds):
    def objective(trial):
        params = card.search_space(trial)
        report, rows, maes = _prune(trial), [], []
        for k, seed in enumerate(seeds):
            r = H.esn_loso(card.build_params(params, seed), seqs, sessions)
            rows.append(r)
            maes.extend(r[:, 0].tolist())
            report(float(np.mean(maes)), k)
        m = np.vstack(rows).mean(0)
        trial.set_user_attr("rmse", float(m[1]))
        trial.set_user_attr("f1", float(m[2]))
        return float(m[0])
    return objective


def run_study(name, objective, n_trials):
    study = optuna.create_study(
        direction="minimize",
        sampler=optuna.samplers.TPESampler(seed=0),
        pruner=optuna.pruners.MedianPruner(n_startup_trials=5, n_warmup_steps=1),
    )
    t0 = time.time()
    study.optimize(objective, n_trials=n_trials)
    b = study.best_trial
    print(f"[{name:12}] best MAE {b.value:.4f}  "
          f"(RMSE {b.user_attrs['rmse']:.4f}, F1 {b.user_attrs['f1']:.3f})  "
          f"{len(study.trials)} trials / {time.time() - t0:.0f}s")
    print(f"[{name:12}]   params: {b.params}")
    return study


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--classic-trials", type=int, default=25,
                    help="trials for RandomForest / XGBoost")
    ap.add_argument("--knn-trials", type=int, default=12,
                    help="kNN trials (small space, and predict is slow)")
    ap.add_argument("--mlp-trials", type=int, default=40)
    ap.add_argument("--esn-trials", type=int, default=30)
    ap.add_argument("--esn-seeds", type=int, default=3,
                    help="reservoir instances averaged per ESN config")
    ap.add_argument("--only", default=None,
                    help="comma-separated model keys/names to (re)tune, e.g. 'esn'; "
                         "others keep their existing best_hparams entry")
    args = ap.parse_args()
    n_trials = {"knn": args.knn_trials, "rf": args.classic_trials,
                "xgb": args.classic_trials, "mlp": args.mlp_trials,
                "esn": args.esn_trials}

    if args.only:
        want = {t.strip().lower() for t in args.only.split(",")}
        keep = lambda c: c.KEY in want or c.NAME.lower() in want
    else:
        keep = lambda c: True

    ex = D.load_examples()
    dev = ex[ex["split"] == "dev"]
    print(f"dev examples: {len(dev)}  ({dev['session'].nunique()} sessions)\n")

    studies = {}   # key -> (card, study)
    for card in M.TABULAR:
        if hasattr(card, "search_space") and keep(card):
            studies[card.KEY] = (card, run_study(
                card.NAME, make_tabular_objective(card, dev), n_trials[card.KEY]))

    seq_cards = [c for c in M.SEQUENCE if keep(c)]
    if seq_cards:
        seqs = D.esn_sequences("dev")
        seeds = list(range(args.esn_seeds))
        for card in seq_cards:
            studies[card.KEY] = (card, run_study(
                card.NAME, make_esn_objective(card, seqs, sorted(seqs), seeds),
                n_trials[card.KEY]))

    if not studies:
        raise SystemExit(f"--only '{args.only}' matched no tunable models")

    out_json = C.DERIVED / "best_hparams.json"
    best = json.loads(out_json.read_text()) if out_json.exists() else {}   # merge
    for key, (card, study) in studies.items():
        entry = {"params": study.best_trial.params, "loso_mae": study.best_value,
                 **study.best_trial.user_attrs}
        if key == "esn":
            entry["esn_seeds"] = args.esn_seeds
        best[key] = entry
        study.trials_dataframe().to_csv(C.DERIVED / f"tune_trials_{key}.csv", index=False)
    out_json.write_text(json.dumps(best, indent=2))
    print(f"\nsaved best hparams -> {out_json}  (updated: {', '.join(studies)})")
    print("saved trial logs  -> derived/tune_trials_<key>.csv")

    # convergence plot reads every model's trial CSV, so partial runs stay complete
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for card in M.ALL:
        path = C.DERIVED / f"tune_trials_{card.KEY}.csv"
        if not path.exists():
            continue
        comp = pd.read_csv(path)
        comp = comp[comp["state"] == "COMPLETE"].sort_values("number")
        if comp.empty:
            continue
        c = np.minimum.accumulate(comp["value"].to_numpy())
        ax.plot(np.arange(1, c.size + 1), c, marker=".",
                color=COLORS.get(card.KEY, "gray"), label=card.NAME)
    ax.set_xlabel("completed trial"); ax.set_ylabel("best-so-far LOSO MAE [m/s]")
    ax.set_title("Optuna tuning — convergence (dev LOSO, all models)")
    ax.grid(alpha=0.3); ax.legend()
    out_png = C.FIGDIR / "slip_tune.png"
    fig.tight_layout(); fig.savefig(out_png, dpi=120)
    print(f"saved plot        -> {out_png}")


if __name__ == "__main__":
    main()
