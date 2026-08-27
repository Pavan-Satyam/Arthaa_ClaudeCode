"""qlib158 IMAX60 factor."""
from __future__ import annotations

import pandas as pd
__alpha_meta__ = {
    'id': 'qlib158_imax60',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{ts\\\\_argmax}(\\\\mathrm{high}, 60) / 60',
    'columns_required': ['high'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 IMAX60 on the supplied OHLCV panel."""
    h = panel['high']
    return ts_argmax(h, 60) / float(60)
