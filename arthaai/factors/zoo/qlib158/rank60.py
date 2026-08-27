"""qlib158 RANK60 factor."""
from __future__ import annotations

import pandas as pd
__alpha_meta__ = {
    'id': 'qlib158_rank60',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{ts\\\\_rank}(\\\\mathrm{close}, 60)',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 RANK60 on the supplied OHLCV panel."""
    c = panel['close']
    return ts_rank(c, 60)
