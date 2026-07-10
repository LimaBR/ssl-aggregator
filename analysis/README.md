# Wheel-slip analysis pipeline

Offline pipeline that turns raw robot telemetry + SSL-Vision detections (captured
by the Phase-1 C++ loggers into PostgreSQL) into **per-wheel slip-velocity
labels**, then trains and compares causal, real-time slip detectors that use
**only onboard sensors** (encoders + IMU). The camera is ground truth for
labelling only — it is never a model input.

- **Target:** `slip_vel = v_encoder − v_ground` (m/s), per wheel. Positive = wheel
  spinning faster than the ground (drive slip); negative = lagging (brake/lock).
- **Detection view:** a slip event is `|slip_vel| > 0.20 m/s`; models are also
  scored by F1 on this threshold.
- **Validation:** leave-one-session-out (LOSO) on the first 80% of each session;
  the **last 20% of every session is a reserved final-test holdout**.

```
telemetry+vision (Postgres)
        │  Stage 1  time-sync (LED ↔ ball)
        │  Stage 2  resample camera pose → 100 Hz  (spline, gap-masked)
        │  Stage 3  inverse kinematics → per-wheel ground speed
        │  Stage 4  slip labels  → derived/slip_labels.parquet
        ▼
   Stage 5 models: slip_tune → slip_compare → slip_final_test
```

## Setup

```bash
# from repo root; venv already provisioned
.venv/bin/python -c "import torch, optuna, xgboost, sklearn"   # sanity check
```

Database credentials are read from the gitignored `.env` at the repo root
(`GRAFANA_PASSWORD`, geometry constants, etc.). Only Stage 1 talks to the
database; Stages 2–5 read the derived parquet files, so the full model workflow
runs offline once Stage 4 has produced `derived/slip_labels.parquet`.

Run every command from the repo root as `.venv/bin/python analysis/<script>.py`.

---

## Stages 1–4 — building the labels

Stages 1–3 are **per session** (`--session` accepts a substring, e.g. a time);
Stage 4 combines all sessions into the single labelled parquet the models use.
Outputs land in `derived/` (parquet) and `figures/` (diagnostic PNGs).

| Stage | Script | What it does | Key flags |
|------|--------|--------------|-----------|
| 1 | `stage1_timesync.py` | Fit `t_capture ≈ a·(packet_id·0.01)+b` from the LED (robot) ↔ ball (camera) square-wave edges; overlay plot proves alignment. | `--session 17:59`, `--list` |
| 2 | `stage2_resample.py` | Smoothing-spline resample of the 60 Hz camera pose onto the 100 Hz packet grid → velocity, heading, ω; >100 ms camera gaps masked out. | `--session`, `--lam`, `--zoom {setpoint,spike}` |
| 3 | `stage3_kinematics.py` | Differential-drive inverse kinematics → per-wheel **ground** speed (`v_tangent ∓ ω·track/2`). | `--session`, `--zoom`, `--center` |
| 4 | `stage4_labels.py` | `slip_vel = v_enc − v_ground` (+ interpretive slip ratio), applies `clean_telemetry`, writes the combined label table. | `--session`, `--all` |

Typical first build:

```bash
.venv/bin/python analysis/stage1_timesync.py --list          # discover sessions
.venv/bin/python analysis/stage1_timesync.py --session 17:59 # then 2,3 per session
.venv/bin/python analysis/stage2_resample.py  --session 17:59
.venv/bin/python analysis/stage3_kinematics.py --session 17:59
.venv/bin/python analysis/stage4_labels.py --all             # → derived/slip_labels.parquet
```

`derived/slip_labels.parquet` is the hand-off point: ~198 k rows with cleaned
telemetry, per-wheel `slip_vel_{left,right}`, and `valid_{left,right}` coverage
masks. Everything in Stage 5 reads only this file.

---

## Stage 5 — the model layer

Refactored into a small, flat architecture: a shared data/harness core, one
thin **card** per model, a **registry**, and three **drivers**. Data flows down;
nothing imports a driver.

```
common.py ─┐                       models_torch.py  (MLPNet, TorchMLPRegressor, TorchESN)
           ▼                                 │
   slip_data.py ── slip_harness.py           │  (torch nets = ExecuTorch export artifacts)
        │  features/sequences  │  LOSO + metrics
        ▼                      ▼             ▼
   model_knn / model_rf / model_xgb / model_mlp / model_esn      ← cards (NAME, KIND, factory)
        └──────────────── slip_models.py (registry) ─────────────┘
                    │             │              │
             slip_compare   slip_tune     slip_final_test          ← drivers
```

### Shared core

- **`slip_data.py`** — the single source of feature/label construction.
  `load_examples()` builds the **tabular** causal-window table with a `split`
  column (`dev`/`test`); `esn_sequences(split)` builds the **raw per-session
  sequences** the ESN needs. Also holds constants (`W`, `DEV_FRAC`, `SLIP_FLAG`,
  `FEATURES`, `SIDES`) and `load_best()` (reads tuned hyperparameters).
- **`slip_harness.py`** — the LOSO evaluators and the `(MAE, RMSE, F1)` metric
  triple. `evaluate()` for tabular models, `esn_loso()` / `esn_final()` for the
  ESN, `fit_predict_tabular()` for the final test.
- **`models_torch.py`** — the PyTorch network classes, kept separate because they
  are the **ExecuTorch export artifacts** (the MLP forward, and the ESN's
  single-timestep `forward(u, x) → (y, x_next)`).

### The 15 causal features (per wheel, 200 ms window)

`w, w_other, sp, sp_err, ax, ay, gz` (instantaneous) and
`w_mean, w_std, sp_mean, ax_std, ay_std, gz_std, w_accel, sp_rate` (window
statistics). All strictly causal (past-only), so the detector is real-time.

### Models (cards)

Every card exposes `NAME`, `KIND`, `KEY`, `build(params)`, `factory()`, and
`search_space(trial)`. `factory()` reads the tuned params from
`derived/best_hparams.json` (falling back to `DEFAULTS`), so **all five models are
tuned the same way** through `slip_tune`. To add one, drop a new `model_*.py`
(with those attributes) and list it in `slip_models.py` — it is then tuned,
compared, and final-tested automatically.

| Card | Model | KIND | Notes |
|------|-------|------|-------|
| `model_knn.py` | k-Nearest Neighbours (distance-weighted) | tabular | simple, non-parametric baseline |
| `model_rf.py`  | Random Forest | tabular | strong classic baseline |
| `model_xgb.py` | XGBoost | tabular | gradient-boosted trees |
| `model_mlp.py` | PyTorch MLP, Huber loss | tabular | ExecuTorch-exportable |
| `model_esn.py` | Echo State Network (reservoir + ridge readout) | **sequence** | stateful/streaming; averaged over reservoir seeds; single-step export for the Pi |

**Why the ESN is a different `KIND`:** it consumes raw sequences (not the
windowed table) and is stateful, so it owns its own `evaluate()` / `final_test()`
and is averaged over several random reservoirs. The tabular cards all share
`slip_harness.evaluate`. Every card's `factory()` reads its tuned hyperparameters
from `derived/best_hparams.json` when present.

### Drivers

Run in this order (each is independent, but tuning informs the other two):

```bash
# 1. optional: tune ALL models' hyperparameters (dev LOSO only; writes best_hparams.json)
.venv/bin/python analysis/slip_tune.py --knn-trials 12 --classic-trials 25 \
                                       --mlp-trials 40 --esn-trials 30 --esn-seeds 3

# 2. compare all five models by LOSO on the dev set (table + bar chart + export check)
.venv/bin/python analysis/slip_compare.py

# 3. one-shot honest evaluation on the reserved last-20% holdout
.venv/bin/python analysis/slip_final_test.py
```

- **`slip_tune.py`** — Optuna (TPE + median pruner), **registry-driven**: it runs
  one study per tunable card, all optimising LOSO-average MAE on **dev only**.
  Tunable knobs — kNN: `k` / weights / metric; RF: trees / depth / leaf /
  features; XGBoost: trees / depth / lr / subsample / colsample / lambda; MLP:
  hidden sizes / lr / weight decay / Huber delta / epochs; ESN: reservoir size /
  spectral radius / leak / input scaling / density / ridge (averaged over
  `--esn-seeds` reservoirs). kNN gets fewer trials (small space, slow `predict`).
  Writes `derived/best_hparams.json` (auto-picked up by every card),
  `derived/tune_trials_<key>.csv`, and `figures/slip_tune.png`. A richer per-trial
  view (history + hyperparameter slices) is in `slip_plot_tune.py`.
- **`slip_compare.py`** — LOSO comparison of every registered model →
  `figures/slip_compare.png`, plus a `torch.export` smoke test confirming the MLP
  and ESN trace cleanly (ExecuTorch-readiness).
- **`slip_final_test.py`** — the **only** script that reads the holdout: refit on
  all dev data, score once on the reserved last-20% → `figures/slip_final_test.png`.
  Run it last, sparingly, after tuning/selection is locked.

### Outputs at a glance

| File | Produced by |
|------|-------------|
| `derived/slip_labels.parquet` | Stage 4 |
| `derived/best_hparams.json`, `derived/tune_trials_<key>.csv` | `slip_tune` |
| `figures/slip_tune.png` (convergence), `figures/slip_tune_detail.png` (slices) | `slip_tune`, `slip_plot_tune` |
| `figures/slip_compare.png` | `slip_compare` |
| `figures/slip_final_test.png` | `slip_final_test` |
| `figures/slip_test_timeseries_<model>.png` | `slip_plot_test` |
| `figures/slip_splits.png`, `figures/slip_pipeline.png` | `slip_plot_splits`, `slip_plot_pipeline` |
