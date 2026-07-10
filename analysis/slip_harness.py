"""Evaluation harness — the LOSO loops and the metric triple shared by every
model card and driver. Two evaluators because the data paths differ:

  * evaluate()  — tabular leave-one-session-out (kNN/RF/XGB/MLP).
  * esn_loso()  — sequence leave-one-session-out for one reservoir (ESN).

Both return a per-fold array of (MAE, RMSE, detection-F1) so the drivers can
report mean ± std the same way regardless of model.
"""
from __future__ import annotations

import numpy as np
import torch
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, root_mean_squared_error, f1_score

import slip_data as D

FEATURES = D.FEATURES


def metrics(y_true, y_pred) -> tuple[float, float, float]:
    """(MAE, RMSE, detection-F1) for slip-velocity predictions."""
    return (mean_absolute_error(y_true, y_pred),
            root_mean_squared_error(y_true, y_pred),
            f1_score(np.abs(y_true) > D.SLIP_FLAG, np.abs(y_pred) > D.SLIP_FLAG))


# --------------------------------------------------------------------------- #
# tabular LOSO
# --------------------------------------------------------------------------- #
def evaluate(factory, dev, report=None) -> np.ndarray:
    """Leave-one-session-out over the dev tabular examples. `factory` is a
    zero-arg callable returning a fresh sklearn-style model. `report(mae, i)` is
    an optional per-fold callback for Optuna pruning. Returns (n_fold, 3)."""
    sessions = sorted(dev["session"].unique())
    out, maes = [], []
    for i, test_s in enumerate(sessions):
        tr = dev[dev["session"] != test_s]
        te = dev[dev["session"] == test_s]
        model = factory()
        model.fit(tr[FEATURES].to_numpy(), tr["y"].to_numpy())
        pred = model.predict(te[FEATURES].to_numpy())
        out.append(metrics(te["y"].to_numpy(), pred))
        maes.append(out[-1][0])
        if report is not None:
            report(float(np.mean(maes)), i)
    return np.array(out)


def fit_predict_tabular(factory, train, test):
    """Fit on `train`, predict on `test` (both example frames). Returns metrics
    on `test`. Used by the final test (fit on all dev, score once on holdout)."""
    model = factory()
    model.fit(train[FEATURES].to_numpy(), train["y"].to_numpy())
    pred = model.predict(test[FEATURES].to_numpy())
    return metrics(test["y"].to_numpy(), pred)


# --------------------------------------------------------------------------- #
# sequence LOSO (ESN)
# --------------------------------------------------------------------------- #
def _fit_esn_readout(esn, seqs, train_ids, scaler):
    train = [(torch.tensor(scaler.transform(seqs[s][sd][0]), dtype=torch.float32),
              torch.tensor(seqs[s][sd][1], dtype=torch.float32),
              torch.tensor(seqs[s][sd][2])) for s, sd in train_ids]
    esn.fit_readout(train)


def _predict_esn(esn, U, scaler):
    return esn.predict_seq(torch.tensor(scaler.transform(U), dtype=torch.float32)).numpy()


def esn_loso(esn, seqs, sessions=None) -> np.ndarray:
    """Sequence LOSO for one reservoir: refit the ridge readout on each train
    split, score the held-out session. Returns (n_fold, 3)."""
    sides = list(D.SIDES)
    if sessions is None:
        sessions = sorted(seqs)
    out = []
    for test_s in sessions:
        train_ids = [(s, sd) for s in sessions if s != test_s for sd in sides]
        scaler = StandardScaler().fit(np.vstack([seqs[s][sd][0] for s, sd in train_ids]))
        _fit_esn_readout(esn, seqs, train_ids, scaler)
        yt, yp = [], []
        for sd in sides:
            U, y, v = seqs[test_s][sd]
            p = _predict_esn(esn, U, scaler)
            m = v.copy(); m[:esn.washout] = False
            yt.append(y[m]); yp.append(p[m])
        out.append(metrics(np.concatenate(yt), np.concatenate(yp)))
    return np.array(out)


def esn_final(esn, dev_seqs, test_seqs) -> tuple[float, float, float]:
    """Fit the readout on all dev sequences, score once on the pooled test
    sequences (per-session last-20%). Returns metrics on the holdout."""
    sides = list(D.SIDES)
    train_ids = [(s, sd) for s in dev_seqs for sd in sides]
    scaler = StandardScaler().fit(np.vstack([dev_seqs[s][sd][0] for s, sd in train_ids]))
    _fit_esn_readout(esn, dev_seqs, train_ids, scaler)
    yt, yp = [], []
    for s in test_seqs:
        for sd in sides:
            U, y, v = test_seqs[s][sd]
            p = _predict_esn(esn, U, scaler)
            m = v.copy(); m[:esn.washout] = False
            yt.append(y[m]); yp.append(p[m])
    return metrics(np.concatenate(yt), np.concatenate(yp))
