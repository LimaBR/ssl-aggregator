"""XGBoost slip regressor (tabular card)."""
from xgboost import XGBRegressor

import slip_data as D

NAME, KIND, KEY = "XGBoost", "tabular", "xgb"
DEFAULTS = dict(n_estimators=400, max_depth=6, learning_rate=0.05,
                subsample=0.8, colsample_bytree=0.8, reg_lambda=1.0)


def build(p):
    return XGBRegressor(
        n_estimators=int(p["n_estimators"]), max_depth=int(p["max_depth"]),
        learning_rate=p["learning_rate"], subsample=p["subsample"],
        colsample_bytree=p["colsample_bytree"], reg_lambda=p["reg_lambda"],
        n_jobs=-1, random_state=0)


def factory():
    return build(D.load_best(KEY, DEFAULTS))


def search_space(trial):
    return dict(
        n_estimators=trial.suggest_int("n_estimators", 100, 600),
        max_depth=trial.suggest_int("max_depth", 3, 10),
        learning_rate=trial.suggest_float("learning_rate", 0.01, 0.3, log=True),
        subsample=trial.suggest_float("subsample", 0.5, 1.0),
        colsample_bytree=trial.suggest_float("colsample_bytree", 0.5, 1.0),
        reg_lambda=trial.suggest_float("reg_lambda", 1e-3, 10.0, log=True))
