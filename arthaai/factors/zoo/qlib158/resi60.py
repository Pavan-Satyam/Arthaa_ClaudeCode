"""qlib158 RESI60 factor."""
from __future__ import annotations

import pandas as pd
__alpha_meta__ = {
    'id': 'qlib158_resi60',
    'theme': ['momentum'],
    'formula_latex': '(\\\\mathrm{close} - \\\\mathrm{ts\\\\_mean}(\\\\mathrm{close}, 60)) / \\\\mathrm{close}',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 RESI60 on the supplied OHLCV panel."""
    c = panel['close']
    return safe_div(c - ts_mean(c, 60), c)
