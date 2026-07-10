"""Random Forest slip regressor (tabular card)."""
from sklearn.ensemble import RandomForestRegressor

import slip_data as D

NAME, KIND, KEY = "RandomForest", "tabular", "rf"
DEFAULTS = dict(n_estimators=80, max_depth=0, min_samples_leaf=5, max_features=1.0)


def build(p):
    md = int(p["max_depth"])
    return RandomForestRegressor(
        n_estimators=int(p["n_estimators"]),
        max_depth=None if md <= 0 else md,
        min_samples_leaf=int(p["min_samples_leaf"]),
        max_features=p["max_features"], n_jobs=-1, random_state=0)


def factory():
    return build(D.load_best(KEY, DEFAULTS))


def search_space(trial):
    return dict(
        n_estimators=trial.suggest_int("n_estimators", 60, 200),
        max_depth=trial.suggest_int("max_depth", 6, 24),
        min_samples_leaf=trial.suggest_int("min_samples_leaf", 1, 20),
        max_features=trial.suggest_float("max_features", 0.3, 1.0))
