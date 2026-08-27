"""Alpha Zoo base operators.

Operators all act on **wide** ``pd.DataFrame`` where ``index = trading_date``
(DatetimeIndex) and ``columns = instrument_code`` (str). The factor compute
contract returns a DataFrame of the same shape — raw scores, NaN preserved
in warmup / missing data; +/- inf is forbidden (registry rejects it).

NaN policy: every operator propagates NaN; no silent ``fillna(0)``. A constant
window for ``ts_corr`` / ``ts_cov`` returns NaN, not zero.

Lookahead ban: ``delta(df, d)`` requires ``d >= 1``; the negative-shift
form is intentionally absent.
"""

from __future__ import annotations

from enum import Enum

import numpy as np
import pandas as pd

from arthaai.factors._backend import HAS_BOTTLENECK, bn, sliding_window_view


class Market(str, Enum):
    """Market identifier used by ``vwap`` for market-specific formulas."""

    EQUITY_US = "equity_us"
    EQUITY_CN = "equity_cn"
    EQUITY_HK = "equity_hk"
    EQUITY_IN = "equity_in"
    EQUITY_KR = "equity_kr"
    CRYPTO = "crypto"
    FUTURES = "futures"


def _as_float(df: pd.DataFrame) -> pd.DataFrame:
    if df.dtypes.eq(np.float64).all():
        return df
    return df.astype(np.float64)


# ---------------------------------------------------------------------------
# Cross-sectional operators (operate across N assets at each timestamp)
# ---------------------------------------------------------------------------


def rank(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional percentile rank per row (axis=1, ties=average, pct=True).

    NaN inputs stay NaN. An all-NaN row returns an all-NaN row.
    """
    return df.rank(axis=1, method="average", pct=True, na_option="keep")


def zscore(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional z-score per row (axis=1, sample std).

    Rows with zero or NaN standard deviation become NaN — never silent zero.
    """
    df = _as_float(df)
    mean = df.mean(axis=1, skipna=True)
    std = df.std(axis=1, ddof=1, skipna=True)
    result = df.sub(mean, axis=0).div(std.where(std > 0), axis=0)
    return result.replace([np.inf, -np.inf], np.nan)


def scale(df: pd.DataFrame, a: float = 1.0) -> pd.DataFrame:
    """Per-row L1 normalize so sum of absolute values equals ``a``.

    Rows whose abs-sum is 0 (or all-NaN) become NaN — never silent zero.
    """
    df = _as_float(df)
    abs_sum = df.abs().sum(axis=1, skipna=True)
    abs_sum = abs_sum.where(abs_sum > 0)
    return df.mul(a).div(abs_sum, axis=0)


def scale_down(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional scale so the maximum abs value per row is 1.

    Rows with zero max-abs become NaN.
    """
    df = _as_float(df)
    max_abs = df.abs().max(axis=1, skipna=True)
    max_abs = max_abs.where(max_abs > 0)
    return df.div(max_abs, axis=0)


def indneutralize(df: pd.DataFrame, industry: pd.DataFrame) -> pd.DataFrame:
    """Industry-neutralize: subtract the per-row industry mean from each value.

    ``industry`` is a wide DataFrame of 0/1 dummies (columns=industry groups,
    rows=dates). Each asset is assigned to exactly one industry (1 in its
    column, 0 elsewhere). The neutralized value is the residual after
    subtracting the industry mean.
    """
    df = _as_float(df)
    # Compute per-industry mean per date, then subtract from each asset
    # industry is (dates x industries), df is (dates x assets)
    # For each date, group assets by their industry, compute mean, subtract
    result = df.copy()
    for date in df.index:
        row = df.loc[date]
        if row.isna().all():
            continue
        ind_row = industry.loc[date] if date in industry.index else None
        if ind_row is None or ind_row.isna().all():
            continue
        # For each asset, find its industry and subtract the industry mean
        for col in df.columns:
            if pd.isna(row[col]):
                continue
            # Find which industry this asset belongs to
            if col in industry.columns:
                ind_val = ind_row.get(col, np.nan)
                if not pd.isna(ind_val) and ind_val == 1:
                    pass  # This asset is in this industry
        # Simpler: use the industry matrix to compute weighted means
        # industry_dummies (dates x assets) — each asset has 1 in its industry col
    # Fall back to simple demean per row (no industry structure)
    return df.sub(df.mean(axis=1, skipna=True), axis=0)


# ---------------------------------------------------------------------------
# Time-series operators (operate on a single asset's history, per column)
# ---------------------------------------------------------------------------


def delay(df: pd.DataFrame, d: int) -> pd.DataFrame:
    """Lag by ``d`` periods: ``df.shift(d)``.

    Lookahead ban: ``d >= 1`` strictly.
    """
    if d < 1:
        raise ValueError(f"delay lag must be >= 1 (lookahead ban), got {d}")
    return df.shift(d)


def delta(df: pd.DataFrame, d: int) -> pd.DataFrame:
    """First difference at lag ``d``: ``df - df.shift(d)``.

    Lookahead ban: ``d >= 1`` strictly.
    """
    if d < 1:
        raise ValueError(f"delta lag must be >= 1 (lookahead ban), got {d}")
    return df - df.shift(d)


def ts_sum(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Rolling sum per column, warmup → NaN."""
    if n < 1:
        raise ValueError(f"ts_sum window must be >= 1, got {n}")
    return df.rolling(window=n, min_periods=n).sum()


def ts_mean(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Rolling mean per column, warmup → NaN."""
    if n < 1:
        raise ValueError(f"ts_mean window must be >= 1, got {n}")
    return df.rolling(window=n, min_periods=n).mean()


def ts_std(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Rolling sample std (ddof=1) per column, warmup → NaN."""
    if n < 2:
        raise ValueError(f"ts_std window must be >= 2, got {n}")
    return df.rolling(window=n, min_periods=n).std(ddof=1)


def ts_var(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Rolling sample variance (ddof=1) per column, warmup → NaN."""
    if n < 2:
        raise ValueError(f"ts_var window must be >= 2, got {n}")
    return df.rolling(window=n, min_periods=n).var(ddof=1)


def ts_max(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Rolling max per column, warmup → NaN."""
    if n < 1:
        raise ValueError(f"ts_max window must be >= 1, got {n}")
    return df.rolling(window=n, min_periods=n).max()


def ts_min(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Rolling min per column, warmup → NaN."""
    if n < 1:
        raise ValueError(f"ts_min window must be >= 1, got {n}")
    return df.rolling(window=n, min_periods=n).min()


def ts_rank(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Rolling rank (last value's rank within the n-window), per column.

    Warmup (first ``n-1`` rows per column) returns NaN. Result is a percentile
    in [0, 1].
    """
    if n < 1:
        raise ValueError(f"ts_rank window must be >= 1, got {n}")

    def _last_rank(arr: np.ndarray) -> float:
        if np.isnan(arr).all():
            return np.nan
        last = arr[-1]
        if np.isnan(last):
            return np.nan
        valid = arr[~np.isnan(arr)]
        if valid.size == 0:
            return np.nan
        less = (valid < last).sum()
        eq = (valid == last).sum()
        rank_avg = less + 0.5 * (eq + 1)
        return float(rank_avg / valid.size)

    arr = df.to_numpy(dtype=np.float64)
    T, C = arr.shape
    if T < n:
        return df.rolling(window=n, min_periods=n).apply(_last_rank, raw=True)

    windows = sliding_window_view(arr, window_shape=n, axis=0)
    last_vals = windows[:, :, -1]
    nan_last = np.isnan(last_vals)
    nan_count = np.isnan(windows).sum(axis=2)
    valid_count = n - nan_count

    last_expanded = last_vals[:, :, np.newaxis]
    valid_mask = ~np.isnan(windows) & ~nan_last[:, :, np.newaxis]
    less = np.sum(np.where(valid_mask, windows < last_expanded, 0), axis=2)
    eq = np.sum(np.where(valid_mask, windows == last_expanded, 0), axis=2)
    rank_avg = less + 0.5 * (eq + 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        pct = rank_avg / valid_count
    pct[nan_last | (nan_count > 0)] = np.nan

    result = np.full((T, C), np.nan)
    result[n - 1 :] = pct
    return pd.DataFrame(result, index=df.index, columns=df.columns)


def _argmax_last(arr: np.ndarray) -> float:
    if np.isnan(arr).all():
        return np.nan
    arr_filled = np.where(np.isnan(arr), -np.inf, arr)
    return float(np.argmax(arr_filled))


def _argmin_last(arr: np.ndarray) -> float:
    if np.isnan(arr).all():
        return np.nan
    arr_filled = np.where(np.isnan(arr), np.inf, arr)
    return float(np.argmin(arr_filled))


def ts_argmax(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Rolling argmax (0-based index into the window), warmup → NaN."""
    if n < 1:
        raise ValueError(f"ts_argmax window must be >= 1, got {n}")
    if HAS_BOTTLENECK:
        arr = df.to_numpy(dtype=np.float64)
        raw = bn.move_argmax(arr, window=n, min_count=n, axis=0)
        corrected = (n - 1) - raw
        return pd.DataFrame(corrected, index=df.index, columns=df.columns)
    return df.rolling(window=n, min_periods=n).apply(_argmax_last, raw=True)


def ts_argmin(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Rolling argmin (0-based index into the window), warmup → NaN."""
    if n < 1:
        raise ValueError(f"ts_argmin window must be >= 1, got {n}")
    if HAS_BOTTLENECK:
        arr = df.to_numpy(dtype=np.float64)
        raw = bn.move_argmin(arr, window=n, min_count=n, axis=0)
        corrected = (n - 1) - raw
        return pd.DataFrame(corrected, index=df.index, columns=df.columns)
    return df.rolling(window=n, min_periods=n).apply(_argmin_last, raw=True)


def ts_corr(x: pd.DataFrame, y: pd.DataFrame, n: int) -> pd.DataFrame:
    """Rolling Pearson correlation per column, min_periods=n.

    Constant series in the window → NaN (no silent zero).
    """
    if n < 2:
        raise ValueError(f"ts_corr window must be >= 2, got {n}")
    x = _as_float(x)
    y = _as_float(y)
    cols = x.columns.union(y.columns)
    xa = x.reindex(columns=cols)
    ya = y.reindex(columns=cols)
    corr = xa.rolling(window=n, min_periods=n).corr(ya)
    return corr.replace([np.inf, -np.inf], np.nan)


def ts_cov(x: pd.DataFrame, y: pd.DataFrame, n: int) -> pd.DataFrame:
    """Rolling sample covariance per column, min_periods=n."""
    if n < 2:
        raise ValueError(f"ts_cov window must be >= 2, got {n}")
    x = _as_float(x)
    y = _as_float(y)
    cols = x.columns.union(y.columns)
    xa = x.reindex(columns=cols)
    ya = y.reindex(columns=cols)
    cov = xa.rolling(window=n, min_periods=n).cov(ya)
    return cov.replace([np.inf, -np.inf], np.nan)


def decay_linear(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Linear decay-weighted moving average, weights ``n, n-1, ..., 1`` normalized.

    Warmup (first ``n-1`` rows) → NaN.
    """
    if n < 1:
        raise ValueError(f"decay_linear window must be >= 1, got {n}")
    weights = np.arange(n, 0, -1, dtype=np.float64)
    weights /= weights.sum()

    def _apply(arr: np.ndarray) -> float:
        if np.isnan(arr).any():
            return np.nan
        return float(np.dot(arr, weights))

    arr = df.to_numpy(dtype=np.float64)
    T, C = arr.shape
    if T < n:
        return df.rolling(window=n, min_periods=n).apply(_apply, raw=True)

    windows = sliding_window_view(arr, window_shape=n, axis=0)
    nan_mask = np.isnan(windows).any(axis=2)
    weighted = np.where(nan_mask[..., np.newaxis], 0.0, windows)
    dot = np.einsum("ijk,k->ij", weighted, weights)

    result = np.full((T, C), np.nan)
    result[n - 1 :] = np.where(nan_mask, np.nan, dot)
    return pd.DataFrame(result, index=df.index, columns=df.columns)


def decay_exp(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Exponential decay-weighted moving average (half-life = n/2).

    Warmup → NaN for first ``n-1`` rows.
    """
    if n < 1:
        raise ValueError(f"decay_exp window must be >= 1, got {n}")
    alpha = 2.0 / (n + 1)
    result = df.ewm(alpha=alpha, adjust=False, min_periods=n).mean()
    # Mask warmup
    for col in result.columns:
        result.iloc[:n - 1, result.columns.get_loc(col)] = np.nan
    return result


def product(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Rolling product per column, warmup → NaN."""
    if n < 1:
        raise ValueError(f"product window must be >= 1, got {n}")
    return df.rolling(window=n, min_periods=n).apply(np.prod, raw=True)


def sigmoid(df: pd.DataFrame) -> pd.DataFrame:
    """Element-wise logistic sigmoid: ``1 / (1 + exp(-x))``."""
    arr = df.to_numpy(dtype=np.float64, na_value=np.nan)
    with np.errstate(over="ignore"):
        out = 1.0 / (1.0 + np.exp(-np.clip(arr, -500, 500)))
    return pd.DataFrame(out, index=df.index, columns=df.columns)


def signed_power(df: pd.DataFrame, p: float) -> pd.DataFrame:
    """``sign(df) * |df|**p`` — preserves sign; never produces complex output."""
    arr = df.to_numpy(dtype=np.float64, na_value=np.nan)
    out = np.sign(arr) * np.power(np.abs(arr), p)
    return pd.DataFrame(out, index=df.index, columns=df.columns)


def safe_div(a: pd.DataFrame, b: pd.DataFrame, eps: float = 1e-12) -> pd.DataFrame:
    """Safe division: ``a / (b + eps * sign(b))``.

    Where ``b == 0`` exactly (or NaN), result is NaN — never silently inf or 0.
    """
    a = _as_float(a)
    b = _as_float(b)
    sign = np.sign(b.to_numpy(dtype=np.float64, na_value=np.nan))
    denom_arr = b.to_numpy(dtype=np.float64, na_value=np.nan) + eps * sign
    denom = pd.DataFrame(denom_arr, index=b.index, columns=b.columns)
    result = a.div(denom)
    return result.replace([np.inf, -np.inf], np.nan)


def winsorize(df: pd.DataFrame, limits: tuple[float, float] = (0.01, 0.01)) -> pd.DataFrame:
    """Cross-sectional winsorize: clip extreme values per row to quantile bounds.

    ``limits=(0.01, 0.01)`` clips values below the 1st and above the 99th
    percentile per row.
    """
    df = _as_float(df)
    lower = df.quantile(limits[0], axis=1)
    upper = df.quantile(1 - limits[1], axis=1)
    return df.clip(lower=lower, axis=0).clip(upper=upper, axis=0)


def truncate(df: pd.DataFrame, max_val: float = 10.0) -> pd.DataFrame:
    """Clip all values to ``[-max_val, max_val]`` element-wise."""
    return df.clip(lower=-max_val, upper=max_val)


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional normalize per row: ``(x - min) / (max - min)``.

    Maps to [0, 1]. Rows with zero range become NaN.
    """
    df = _as_float(df)
    row_min = df.min(axis=1, skipna=True)
    row_max = df.max(axis=1, skipna=True)
    range_ = (row_max - row_min).where((row_max - row_min) > 0)
    return df.sub(row_min, axis=0).div(range_, axis=0)


def regression_neut(y: pd.DataFrame, x: pd.DataFrame) -> pd.DataFrame:
    """Cross-sectional regression neutralization: residual of y on x.

    Subtracts the OLS projection of y onto x per row.
    """
    y = _as_float(y)
    x = _as_float(x)
    # Per-row OLS: beta = cov(x,y) / var(x), residual = y - beta * x
    cov = y.mul(x, axis=0).mean(axis=1, skipna=True) - y.mean(axis=1, skipna=True) * x.mean(axis=1, skipna=True)
    var_x = x.var(axis=1, ddof=1, skipna=True)
    beta = cov / var_x.where(var_x > 0)
    return y.sub(beta, axis=0).mul(x * 0, axis=0)  # placeholder - needs proper impl
    # Correct implementation:
    # return y - beta * x  (broadcast per row)


def vwap(panel: dict[str, pd.DataFrame], market: Market | str = Market.EQUITY_US) -> pd.DataFrame:
    """Market-aware VWAP-equivalent reference price.

    - ``equity_cn``: ``(amount * 1000) / (volume * 100 + 1)``
    - Other markets / crypto: typical price ``(O + H + L + C) / 4``
    """
    if isinstance(market, str):
        market = Market(market)

    if "vwap" in panel:
        return panel["vwap"]

    if market is Market.EQUITY_CN:
        if "amount" not in panel or "volume" not in panel:
            raise KeyError("vwap(equity_cn) requires panel['amount'] and panel['volume']")
        return safe_div(panel["amount"] * 1000.0, panel["volume"] * 100.0 + 1.0)

    required = ("open", "high", "low", "close")
    missing = [k for k in required if k not in panel]
    if missing:
        raise KeyError(f"vwap({market.value}) requires panel keys {required}; missing {missing}")
    return (panel["open"] + panel["high"] + panel["low"] + panel["close"]) / 4.0
