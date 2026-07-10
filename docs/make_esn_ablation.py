#!/usr/bin/env python3
"""Gera figures/esn_reservoir_size.png — ablação do tamanho do reservatório do ESN.

Valores medidos por varredura controlada (LOSO no dev, com os demais
hiperparâmetros do reservatório fixos nos melhores do tune de 60 trials).
Fonte: scripts test_arch.py (n_res 350–650) + esn_sweep.py (n_res 650–950).

Run:  .venv/bin/python docs/make_esn_ablation.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

FIG = Path(__file__).resolve().parent.parent / "analysis" / "figures"

nres = [350, 450, 550, 650, 750, 850, 950]
mae = [0.0390, 0.0376, 0.0346, 0.0334, 0.0334, 0.0328, 0.0323]
f1 = [0.849, 0.850, 0.869, 0.878, 0.874, 0.873, 0.879]

fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.2))
a1.plot(nres, mae, "o-", color="tab:purple", lw=2)
a1.scatter([950], [0.0323], s=220, marker="*", color="gold", edgecolor="black",
           zorder=5, label="adotado (950)")
a1.set_xlabel("n_res (tamanho do reservatório)"); a1.set_ylabel("LOSO MAE [m/s]")
a1.set_title("MAE (menor é melhor)"); a1.grid(alpha=.3); a1.legend()
a2.plot(nres, f1, "o-", color="tab:purple", lw=2)
a2.scatter([950], [0.879], s=220, marker="*", color="gold", edgecolor="black", zorder=5)
a2.set_xlabel("n_res (tamanho do reservatório)"); a2.set_ylabel("detecção F1")
a2.set_title("F1 de detecção (maior é melhor)"); a2.grid(alpha=.3)
fig.suptitle("ESN — efeito do tamanho do reservatório  (dev-LOSO; demais "
             "hiperparâmetros fixos)", fontweight="bold")
fig.tight_layout()
out = FIG / "esn_reservoir_size.png"
fig.savefig(out, dpi=120)
print(f"saved -> {out}")
