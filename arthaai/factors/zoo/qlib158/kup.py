"""qlib158 KUP factor."""
from __future__ import annotations

import pandas as pd
__alpha_meta__ = {
    'id': 'qlib158_kup',
    'theme': ['microstructure'],
    'formula_latex': '(\\\\mathrm{high} - \\\\max(\\\\mathrm{open}, \\\\mathrm{close})) / \\\\mathrm{open}',
    'columns_required': ['open', 'high', 'close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 1,
    'min_warmup_bars': 1,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 KUP on the supplied OHLCV panel."""
    o = panel['open']
    c = panel['close']
    h = panel['high']
    upper = o.where(o >= c, c)
    return safe_div(h - upper, o)
