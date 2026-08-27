"""qlib158 RSV60 factor."""
from __future__ import annotations

import pandas as pd
__alpha_meta__ = {
    'id': 'qlib158_rsv60',
    'theme': ['momentum'],
    'formula_latex': '(\\\\mathrm{close} - \\\\mathrm{ts\\\\_min}(\\\\mathrm{low}, 60)) / (\\\\mathrm{ts\\\\_max}(\\\\mathrm{high}, 60) - \\\\mathrm{ts\\\\_min}(\\\\mathrm{low}, 60))',
    'columns_required': ['high', 'low', 'close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 RSV60 on the supplied OHLCV panel."""
    c = panel['close']
    h = panel['high']
    lo = panel['low']
    hh = ts_max(h, 60)
    ll = ts_min(lo, 60)
    return safe_div(c - ll, hh - ll)
std5.py — std60.py (价格标准差比)
