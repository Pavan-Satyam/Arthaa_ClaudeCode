"""qlib158 BETA60: (close_t - close_{t-60}) / (60 * close)."""
from __future__ import annotations

import pandas as pd
from arthaai.factors.base import safe_div, delta

__alpha_meta__ = {
    'id': 'qlib158_beta60',
    'theme': ['momentum'],
    'formula_latex': '(close_t - close_{t-60}) / (60 * close)',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel['close']
    return safe_div(delta(c, 60), c) / float(60)
