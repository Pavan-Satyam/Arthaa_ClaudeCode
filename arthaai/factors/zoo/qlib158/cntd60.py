"""qlib158 CNTD60."""
from __future__ import annotations

import pandas as pd

__alpha_meta__ = {
    'id': 'qlib158_cntd60',
    'theme': ['reversal'],
    'formula_latex': 'cntd(60)',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel['close']
    up = (c > c.shift(1)).rolling(60).sum()
    down = (c < c.shift(1)).rolling(60).sum()
    return (up - down) / float(60)
