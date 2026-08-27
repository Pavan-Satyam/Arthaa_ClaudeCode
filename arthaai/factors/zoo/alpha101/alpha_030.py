"""Kakushadze Alpha #30.

Formula (paper appendix): ((1-rank(sign(d1)+sign(d2)+sign(d3))) * sum(volume,5)) / sum(volume,20)
Source: Kakushadze (2015), "101 Formulaic Alphas", arXiv:1601.00991, eq. 30.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from arthaai.factors.base import (
    rank,
    safe_div,
)

__alpha_meta__ = {
    'id': 'alpha101_030',
    'nickname': 'Kakushadze Alpha #30',
    'theme': ['volume', 'reversal'],
    'formula_latex': '((1-rank(sign(d1)+sign(d2)+sign(d3))) * sum(volume,5)) / sum(volume,20)',
    'columns_required': ['close', 'volume'],
    'extras_required': [],
    'requires_sector': False,
    'universe': ['equity_us', 'equity_in', 'equity_kr'],
    'frequency': ['1D'],
    'decay_horizon': 5,
    'min_warmup_bars': 25,
    'notes': '',
}


def compute(panel: dict) -> pd.DataFrame:
    """Compute the alpha on the OHLCV+ panel and return a wide DataFrame."""
    close = panel["close"]
    volume = panel["volume"]

    d1 = close - close.shift(1)
    d2 = close.shift(1) - close.shift(2)
    d3 = close.shift(2) - close.shift(3)
    sign_sum = np.sign(d1) + np.sign(d2) + np.sign(d3)
    out = (1.0 - rank(sign_sum)) * safe_div(volume.rolling(5, min_periods=5).sum(), volume.rolling(20, min_periods=20).sum())
    return out
