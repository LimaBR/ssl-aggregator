"""Model registry — the single list every driver (compare/tune/final_test)
iterates, so adding or retuning a model happens in exactly one place.

Each card exposes: NAME, KIND ('tabular' | 'sequence'), factory(). Tabular cards
plug into slip_harness.evaluate; sequence cards own their evaluate()/final_test().
"""
import model_knn
import model_rf
import model_xgb
import model_mlp
import model_esn

TABULAR = [model_knn, model_rf, model_xgb, model_mlp]
SEQUENCE = [model_esn]
ALL = TABULAR + SEQUENCE
