"""qlib158 CNTD10."""
from __future__ import annotations

import pandas as pd

__alpha_meta__ = {
    'id': 'qlib158_cntd10',
    'theme': ['reversal'],
    'formula_latex': 'cntd(10)',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 10,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel['close']
    up = (c > c.shift(1)).rolling(10).sum()
    down = (c < c.shift(1)).rolling(10).sum()
    return (up - down) / float(10)
