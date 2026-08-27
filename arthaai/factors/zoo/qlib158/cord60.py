"""qlib158 CORD60 factor."""
from __future__ import annotations

import pandas as pd
__alpha_meta__ = {
    'id': 'qlib158_cord60',
    'theme': ['volume', 'microstructure'],
    'formula_latex': '\\\\mathrm{ts\\\\_corr}(\\\\mathrm{close}/\\\\mathrm{close}_{{-1}}, \\\\log((\\\\mathrm{volume}+1)/(\\\\mathrm{volume}_{{-1}}+1)), 60)',
    'columns_required': ['close', 'volume'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 CORD60 on the supplied OHLCV panel."""
    c = panel['close']
    v = panel['volume']
    c_ret = safe_div(c, c.shift(1))
    v_ret = safe_div(v + 1.0, v.shift(1) + 1.0)
    logvr = np.log(v_ret)
    return ts_corr(c_ret, logvr, 60)
corr5.py — corr60.py (价量相关性)
