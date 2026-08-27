"""qlib158 BETA5: (close_t - close_{t-5}) / (5 * close)."""
from __future__ import annotations

import pandas as pd
from arthaai.factors.base import safe_div, delta

__alpha_meta__ = {
    'id': 'qlib158_beta5',
    'theme': ['momentum'],
    'formula_latex': '(close_t - close_{t-5}) / (5 * close)',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 5,
    'min_warmup_bars': 5,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel['close']
    return safe_div(delta(c, 5), c) / float(5)
