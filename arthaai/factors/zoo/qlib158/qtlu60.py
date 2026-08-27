"""qlib158 QTLU60 factor."""
from __future__ import annotations

import pandas as pd
__alpha_meta__ = {
    'id': 'qlib158_qtlu60',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{quantile}_{{0.8}}(\\\\mathrm{close}, 60) / \\\\mathrm{close}',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 QTLU60 on the supplied OHLCV panel."""
    c = panel['close']
    q = c.rolling(window=60, min_periods=60).quantile(0.8)
    return safe_div(q, c)
