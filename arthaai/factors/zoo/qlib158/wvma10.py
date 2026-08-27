"""qlib158 WVMA10 factor."""
from __future__ import annotations

import pandas as pd
__alpha_meta__ = {
    'id': 'qlib158_wvma10',
    'theme': ['volume', 'volatility'],
    'formula_latex': '\\\\mathrm{ts\\\\_std}(\\\\mathrm{ret}\\\\cdot v, 10) / \\\\mathrm{ts\\\\_mean}(|\\\\mathrm{ret}|\\\\cdot v, 10)',
    'columns_required': ['close', 'volume'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 10,
    'min_warmup_bars': 10,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 WVMA10 on the supplied OHLCV panel."""
    c = panel['close']
    v = panel['volume']
    ret = safe_div(c, c.shift(1)) - 1.0
    rv = ret * v
    arv = ret.abs() * v
    return safe_div(ts_std(rv, 10), ts_mean(arv, 10))
