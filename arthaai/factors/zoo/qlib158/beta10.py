"""qlib158 BETA10: (close_t - close_{t-10}) / (10 * close)."""
from __future__ import annotations

import pandas as pd
from arthaai.factors.base import safe_div, delta

__alpha_meta__ = {
    'id': 'qlib158_beta10',
    'theme': ['momentum'],
    'formula_latex': '(close_t - close_{t-10}) / (10 * close)',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 10,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel['close']
    return safe_div(delta(c, 10), c) / float(10)
