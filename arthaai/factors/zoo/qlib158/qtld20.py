"""qlib158 QTLD20 factor."""
from __future__ import annotations

import pandas as pd
__alpha_meta__ = {
    'id': 'qlib158_qtld20',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{quantile}_{{0.2}}(\\\\mathrm{close}, 20) / \\\\mathrm{close}',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 20,
    'min_warmup_bars': 20,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 QTLD20 on the supplied OHLCV panel."""
    c = panel['close']
    q = c.rolling(window=20, min_periods=20).quantile(0.2)
    return safe_div(q, c)
