"""kNN slip regressor (tabular card)."""
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import slip_data as D

NAME, KIND, KEY = "kNN", "tabular", "knn"
DEFAULTS = dict(n_neighbors=15, weights="distance", p=2)


def build(p):
    return make_pipeline(
        StandardScaler(),
        KNeighborsRegressor(n_neighbors=int(p["n_neighbors"]), weights=p["weights"],
                            p=int(p["p"]), n_jobs=-1))


def factory():
    return build(D.load_best(KEY, DEFAULTS))


def search_space(trial):
    return dict(
        n_neighbors=trial.suggest_int("n_neighbors", 3, 40),
        weights=trial.suggest_categorical("weights", ["uniform", "distance"]),
        p=trial.suggest_categorical("p", [1, 2]))
