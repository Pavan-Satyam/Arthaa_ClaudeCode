"""qlib158 MAX60 factor."""
from __future__ import annotations

import pandas as pd
__alpha_meta__ = {
    'id': 'qlib158_max60',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{ts\\\\_max}(\\\\mathrm{high}, 60) / \\\\mathrm{close}',
    'columns_required': ['high', 'close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 MAX60 on the supplied OHLCV panel."""
    h = panel['high']
    c = panel['close']
    return safe_div(ts_max(h, 60), c)
