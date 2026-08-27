"""qlib158 IMXD60 factor."""
from __future__ import annotations

import pandas as pd
__alpha_meta__ = {
    'id': 'qlib158_imxd60',
    'theme': ['momentum'],
    'formula_latex': '(\\\\mathrm{ts\\\\_argmax}(\\\\mathrm{high}, 60) - \\\\mathrm{ts\\\\_argmin}(\\\\mathrm{low}, 60)) / 60',
    'columns_required': ['high', 'low'],
    'universe': ['equity_us', 'equity_cn', 'equity_hk', 'equity_in', 'equity_kr'],
    'frequency': ['1d'],
    'decay_horizon': 60,
    'min_warmup_bars': 60,
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return qlib158 IMXD60 on the supplied OHLCV panel."""
    h = panel['high']
    lo = panel['low']
    return (ts_argmax(h, 60) - ts_argmin(lo, 60)) / float(60)
klen.py, kmid.py, kup.py, klow.py, kmid2.py, ksft.py, klow2.py, kup2.py, ksft2.py (K线形态)
