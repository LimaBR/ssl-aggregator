"""MLP slip regressor (tabular card).

PyTorch feed-forward net (Huber loss), structured for ExecuTorch export. The
network class lives in models_torch; this card wires the chosen / tuned
hyperparameters (from derived/best_hparams.json when present) into a factory.
"""
import torch

import slip_data as D
import models_torch as MT

NAME, KIND, KEY = "MLP", "tabular", "mlp"
DEFAULTS = dict(h1=64, h2=32, lr=1e-3, weight_decay=1e-4, huber_delta=0.1, epochs=40)


def build(p):
    return MT.TorchMLPRegressor(
        hidden=(int(p["h1"]), int(p["h2"])), lr=p["lr"],
        weight_decay=p["weight_decay"], huber_delta=p["huber_delta"],
        epochs=int(p["epochs"]), seed=0)


def factory():
    return build(D.load_best(KEY, DEFAULTS))


def search_space(trial):
    return dict(
        h1=trial.suggest_categorical("h1", [64, 128, 256]),
        h2=trial.suggest_categorical("h2", [32, 64, 128]),
        lr=trial.suggest_float("lr", 1e-4, 5e-3, log=True),
        weight_decay=trial.suggest_float("weight_decay", 1e-6, 1e-2, log=True),
        huber_delta=trial.suggest_float("huber_delta", 0.02, 0.5, log=True),
        epochs=trial.suggest_int("epochs", 20, 80))


def export_example():
    """(fresh module, example_args) for torch.export / ExecuTorch."""
    p = D.load_best(KEY, DEFAULTS)
    net = MT.MLPNet(len(D.FEATURES), (int(p["h1"]), int(p["h2"])))
    net.eval()
    return net, (torch.zeros(1, len(D.FEATURES)),)
