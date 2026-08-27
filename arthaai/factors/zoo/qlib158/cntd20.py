"""qlib158 CNTD20."""
from __future__ import annotations

import pandas as pd

__alpha_meta__ = {
    'id': 'qlib158_cntd20',
    'theme': ['reversal'],
    'formula_latex': 'cntd(20)',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 20,
    'min_warmup_bars': 20,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel['close']
    up = (c > c.shift(1)).rolling(20).sum()
    down = (c < c.shift(1)).rolling(20).sum()
    return (up - down) / float(20)
