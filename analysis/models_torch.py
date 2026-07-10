"""PyTorch slip models, structured for ExecuTorch export.

- MLP  : feedforward regressor (Huber loss). Inference forward is a plain
         fixed-shape tensor op -> torch.export friendly.
- ESN  : reservoir (fixed buffers) + ridge-fit linear readout. Training runs the
         reservoir over sequences; the exported artefact is the single-timestep
         `forward(u, x) -> (y, x_next)` so state lives in the caller's loop
         (the natural streaming pattern for a Raspberry Pi).
"""
from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn
from sklearn.preprocessing import StandardScaler


# --------------------------------------------------------------------------- #
# MLP
# --------------------------------------------------------------------------- #
class MLPNet(nn.Module):
    def __init__(self, n_in, hidden=(64, 32)):
        super().__init__()
        layers, d = [], n_in
        for h in hidden:
            layers += [nn.Linear(d, h), nn.ReLU()]
            d = h
        layers.append(nn.Linear(d, 1))
        self.net = nn.Sequential(*layers)

    def forward(self, x):                 # (batch, n_in) -> (batch,)
        return self.net(x).squeeze(-1)


class TorchMLPRegressor:
    """sklearn-style wrapper (fit/predict) so it drops into the LOSO harness."""

    def __init__(self, hidden=(64, 32), lr=1e-3, epochs=40, batch=4096,
                 weight_decay=1e-4, huber_delta=0.1, seed=0):
        self.hidden, self.lr, self.epochs, self.batch = hidden, lr, epochs, batch
        self.weight_decay, self.huber_delta, self.seed = weight_decay, huber_delta, seed

    def fit(self, X, y):
        torch.manual_seed(self.seed)
        self.scaler = StandardScaler().fit(X)
        Xs = torch.tensor(self.scaler.transform(X), dtype=torch.float32)
        yt = torch.tensor(np.asarray(y), dtype=torch.float32)
        self.net = MLPNet(X.shape[1], self.hidden)
        opt = torch.optim.Adam(self.net.parameters(), lr=self.lr,
                               weight_decay=self.weight_decay)
        loss_fn = nn.HuberLoss(delta=self.huber_delta)
        n = len(Xs)
        self.net.train()
        for _ in range(self.epochs):
            perm = torch.randperm(n)
            for i in range(0, n, self.batch):
                idx = perm[i:i + self.batch]
                opt.zero_grad()
                loss_fn(self.net(Xs[idx]), yt[idx]).backward()
                opt.step()
        self.net.eval()
        return self

    def predict(self, X):
        Xs = torch.tensor(self.scaler.transform(X), dtype=torch.float32)
        with torch.no_grad():
            return self.net(Xs).numpy()

    def export_example(self):
        """(module, example_args) for torch.export / ExecuTorch."""
        return self.net, (torch.zeros(1, self.scaler.mean_.shape[0]),)


# --------------------------------------------------------------------------- #
# ESN
# --------------------------------------------------------------------------- #
class TorchESN(nn.Module):
    def __init__(self, n_in, n_res=300, sr=0.9, in_scale=0.5, leak=0.3,
                 density=0.1, ridge=1e-2, washout=50, seed=0):
        super().__init__()
        g = torch.Generator().manual_seed(seed)
        Win = (torch.rand(n_res, n_in + 1, generator=g) * 2 - 1) * in_scale
        W = (torch.rand(n_res, n_res, generator=g) * 2 - 1)
        W = W * (torch.rand(n_res, n_res, generator=g) < density)
        W = W * (sr / torch.linalg.eigvals(W).abs().max())
        self.register_buffer("Win", Win.float())
        self.register_buffer("W", W.float())
        self.register_buffer("Wout", torch.zeros(n_in + 1 + n_res))
        self.leak, self.n_res, self.n_in = leak, n_res, n_in
        self.washout, self.ridge = washout, ridge

    @torch.no_grad()
    def _states(self, U):                 # U:(T,n_in) -> extended states (T,1+n_in+n_res)
        T = U.shape[0]
        drive = torch.cat([torch.ones(T, 1), U], 1) @ self.Win.T   # vectorised input part
        x = torch.zeros(self.n_res)
        X = torch.empty(T, self.n_res)
        for t in range(T):
            x = (1 - self.leak) * x + self.leak * torch.tanh(drive[t] + self.W @ x)
            X[t] = x
        return torch.cat([torch.ones(T, 1), U, X], 1)

    @torch.no_grad()
    def fit_readout(self, seqs):          # seqs: list of (U, y, valid) tensors
        d = self.n_in + 1 + self.n_res
        A, B = torch.zeros(d, d), torch.zeros(d)
        for U, y, v in seqs:
            E = self._states(U)
            m = v.clone(); m[:self.washout] = False
            A += E[m].T @ E[m]
            B += E[m].T @ y[m]
        self.Wout = torch.linalg.solve(A + self.ridge * torch.eye(d), B)

    @torch.no_grad()
    def predict_seq(self, U):
        return self._states(U) @ self.Wout

    def forward(self, u, x):              # SINGLE STEP — export-ready
        pre = self.Win @ torch.cat([torch.ones(1), u]) + self.W @ x
        x_next = (1 - self.leak) * x + self.leak * torch.tanh(pre)
        y = self.Wout @ torch.cat([torch.ones(1), u, x_next])
        return y, x_next

    def export_example(self):
        return self, (torch.zeros(self.n_in), torch.zeros(self.n_res))
