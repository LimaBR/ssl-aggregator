"""Echo State Network slip regressor (sequence card).

Unlike the tabular cards, the ESN consumes raw per-session sequences and is
stateful, so it owns its own evaluation. A reservoir is a random draw, so
`evaluate` averages several reservoir seeds per fold. The exported artefact is
the single-timestep step function (state passed in/out) for streaming inference
on the Raspberry Pi.
"""
import numpy as np
import torch

import slip_data as D
import slip_harness as H
import models_torch as MT

NAME, KIND, KEY = "ESN", "sequence", "esn"

DEFAULTS = dict(n_res=300, sr=0.9, in_scale=0.5, leak=0.3, density=0.1, ridge=1e-2)
SEEDS = (0, 1, 2)   # reservoir instances averaged for a stable score


def params():
    return D.load_best(KEY, DEFAULTS)


def build_params(p, seed=0):
    return MT.TorchESN(
        n_in=D.ESN_N_IN, n_res=int(p["n_res"]), sr=p["sr"],
        in_scale=p["in_scale"], leak=p["leak"], density=p["density"],
        ridge=p["ridge"], seed=seed)


def build(seed=0):
    return build_params(params(), seed)


def search_space(trial):
    return dict(
        n_res=trial.suggest_categorical("n_res", [350, 450, 550, 650, 750, 850, 950]),
        sr=trial.suggest_float("sr", 0.3, 1.3),
        leak=trial.suggest_float("leak", 0.05, 1.0),
        in_scale=trial.suggest_float("in_scale", 0.1, 1.5, log=True),
        density=trial.suggest_float("density", 0.05, 0.3),
        ridge=trial.suggest_float("ridge", 1e-6, 1e0, log=True))


def evaluate(dev_seqs=None, seeds=SEEDS) -> np.ndarray:
    """Sequence LOSO, averaged over reservoir seeds. Returns per-fold (n_fold, 3)
    so it drops into the same table as the tabular models."""
    if dev_seqs is None:
        dev_seqs = D.esn_sequences("dev")
    sessions = sorted(dev_seqs)
    per_seed = [H.esn_loso(build(s), dev_seqs, sessions) for s in seeds]
    return np.stack(per_seed).mean(0)


def final_test(dev_seqs=None, test_seqs=None, seeds=SEEDS) -> np.ndarray:
    """Fit on all dev sequences, score once on the holdout, averaged over seeds.
    Returns per-seed (n_seed, 3)."""
    if dev_seqs is None:
        dev_seqs = D.esn_sequences("dev")
    if test_seqs is None:
        test_seqs = D.esn_sequences("test")
    return np.array([H.esn_final(build(s), dev_seqs, test_seqs) for s in seeds])


def export_example():
    """(fresh module, example_args) for torch.export / ExecuTorch."""
    esn = build(0)
    esn.eval()
    return esn, (torch.zeros(D.ESN_N_IN), torch.zeros(esn.n_res))
