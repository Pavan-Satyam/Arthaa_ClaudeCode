"""qlib158 BETA20: (close_t - close_{t-20}) / (20 * close)."""
from __future__ import annotations

import pandas as pd
from arthaai.factors.base import safe_div, delta

__alpha_meta__ = {
    'id': 'qlib158_beta20',
    'theme': ['momentum'],
    'formula_latex': '(close_t - close_{t-20}) / (20 * close)',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 20,
    'min_warmup_bars': 20,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel['close']
    return safe_div(delta(c, 20), c) / float(20)
