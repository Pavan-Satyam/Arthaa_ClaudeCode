"""qlib158 RSQR30 factor."""
from __future__ import annotations

import pandas as pd
__alpha_meta__ = {
    'id': 'qlib158_rsqr30',
    'theme': ['momentum'],
    'formula_latex': '\\\\mathrm{ts\\\\_corr}(\\\\mathrm{close}, t, 30)^2',
    'columns_required': ['close'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 30,
    'min_warmup_bars': 30,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 RSQR30 on the supplied OHLCV panel."""
    c = panel['close']
    t_arr = np.arange(len(c.index), dtype=np.float64)
    t_df = pd.DataFrame(np.broadcast_to(t_arr[:, None], c.shape).copy(), index=c.index, columns=c.columns)
    corr = ts_corr(c, t_df, 30)
    return corr * corr
