"""Alpha Zoo factor engine — 5 zoos, 460+ alphas.

Base operators in ``base.py``, registry in ``registry.py``, panel construction
in ``panel.py``, IC evaluation in ``eval.py``. Factor implementations live in
``zoo/<zoo_id>/<alpha_id>.py``, one file per alpha, auto-discovered via AST scan.
"""

from arthaai.factors.base import (
    Market,
    decay_exp,
    decay_linear,
    delay,
    delta,
    indneutralize,
    normalize,
    product,
    rank,
    regression_neut,
    safe_div,
    scale,
    scale_down,
    signed_power,
    sigmoid,
    truncate,
    ts_argmax,
    ts_argmin,
    ts_corr,
    ts_cov,
    ts_max,
    ts_mean,
    ts_min,
    ts_rank,
    ts_std,
    ts_sum,
    ts_var,
    vwap,
    winsorize,
    zscore,
)

__all__ = [
    "Market",
    "decay_exp", "decay_linear", "delay", "delta",
    "indneutralize", "normalize", "product", "rank",
    "regression_neut", "safe_div", "scale", "scale_down",
    "signed_power", "sigmoid", "truncate", "ts_argmax", "ts_argmin",
    "ts_corr", "ts_cov", "ts_max", "ts_mean", "ts_min",
    "ts_rank", "ts_std", "ts_sum", "ts_var", "vwap", "winsorize", "zscore",
]
