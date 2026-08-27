"""qlib158 MIN60 factor."""
from __future__ import annotations

import pandas as pd
__alpha_meta__ = {
    'id': 'qlib158_min60',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{ts\\\\_min}(\\\\mathrm{low}, 60) / \\\\mathrm{close}',
    'columns_required': ['low', 'close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 MIN60 on the supplied OHLCV panel."""
    lo = panel['low']
    c = panel['close']
    return safe_div(ts_min(lo, 60), c)
