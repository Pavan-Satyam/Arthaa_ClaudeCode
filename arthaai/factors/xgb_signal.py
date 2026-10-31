"""Pre-registered XGBoost-over-factor-zoo signal (E3 family ``xgb_zoo``).

Implements the architecture doc's own recipe — "Alpha factors -> tabular model
(XGBoost) -> signal -> backtest gate" — under the E3 protocol's look-ahead rules.
Three deliberate choices (pre-registered before the first run):

1. **Target is volatility-adjusted**, not raw forward return. The frozen universe
   mixes high-beta tech equities with low-vol commodity ETFs, so a pooled model on
   raw forward returns just learns to predict high-vol regimes. Target =
   forward return / trailing 20-day realized vol, with an asset-class categorical
   feature so equities and commodity ETFs are distinguishable.
2. **Features are strictly backward-looking** — trailing returns, realized vol,
   moving-average distance, raw ``tsmom``/``xsmom`` values, and the qlib158
   beta/corr/cord windows. Composite/meta-signals (``ic_composite``) are excluded
   because their weights are fit on the whole panel and would leak across the
   walk-forward boundary.
3. **Positions come from EMA + hysteresis**, not a naive ``predict() > 0``
   threshold: enter long when the 5-day smoothed score exceeds the 60th percentile
   of its own trailing history, exit only below the 40th. This controls turnover so
   the 10 bps round-trip cost doesn't bleed the edge.

Everything here is causal; the model is fit on an expanding in-sample window and
predicts into the next out-of-sample slice with no tuning on it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Pre-registered configuration (frozen; do not tune on an OOS window).
HORIZON = 1
VOL_WINDOW = 20
ENTER_QUANTILE = 0.60
EXIT_QUANTILE = 0.40
SMOOTH_SPAN = 5
MIN_HISTORY = 60
# Trailing window for the hysteresis percentile bands (~1 trading year). A bounded
# window keeps the bands causal and O(n*W); an expanding quantile is O(n^2).
HYSTERESIS_WINDOW = 252
INITIAL_TRAIN_FRAC = 0.50
STEP_FRAC = 0.10

# qlib158 momentum-zoo factors (pure backward-looking price windows).
ZOO_FACTOR_IDS = [
    "qlib158_beta5", "qlib158_beta10", "qlib158_beta20", "qlib158_beta30", "qlib158_beta60",
    "qlib158_corr5", "qlib158_corr10", "qlib158_corr20", "qlib158_corr30", "qlib158_corr60",
    "qlib158_cord5", "qlib158_cord10", "qlib158_cord20", "qlib158_cord30", "qlib158_cord60",
]

XGB_PARAMS = {
    "max_depth": 3,
    "n_estimators": 300,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_alpha": 0.0,
    "reg_lambda": 1.0,
    "objective": "reg:squarederror",
    "tree_method": "hist",
    "random_state": 0,
}

# Commodity/energy ETFs in the frozen universe; everything else is treated as equity.
COMMODITY_ETFS = frozenset({
    "GLD", "SLV", "USO", "DBC", "PPLT", "PALL", "GDX", "GDXJ", "UNG", "UNL",
    "BNO", "UCO", "SCO", "WEAT", "CORN", "SOYB", "CPER",
})


def asset_class(symbol: str) -> str:
    """Coarse asset class for the model's categorical feature."""
    return "commodity" if str(symbol).upper() in COMMODITY_ETFS else "equity"


def vol_adjusted_forward_return(
    close: pd.DataFrame,
    *,
    horizon: int = HORIZON,
    vol_window: int = VOL_WINDOW,
) -> pd.DataFrame:
    """Forward return divided by trailing realized vol (the pre-registered target)."""
    fwd = close.shift(-horizon) / close - 1.0
    vol = close.pct_change(fill_method=None).rolling(vol_window).std(ddof=0)
    return fwd / vol.replace(0.0, np.nan)


def hysteresis_positions(
    score: pd.Series,
    *,
    enter_quantile: float = ENTER_QUANTILE,
    exit_quantile: float = EXIT_QUANTILE,
    smooth: int = SMOOTH_SPAN,
    min_history: int = MIN_HISTORY,
) -> pd.Series:
    """Map a raw score to 0/1 positions via EMA smoothing + trailing hysteresis.

    The percentile bands are computed on a **bounded trailing** window, so a date's
    band never sees future scores and the cost stays O(n*W) rather than O(n^2). Flat
    until ``min_history`` observations.
    """
    s = pd.to_numeric(score, errors="coerce").dropna()
    if s.empty:
        return pd.Series(dtype="float64")
    smoothed = s.ewm(span=smooth, min_periods=1).mean()
    hi = smoothed.rolling(HYSTERESIS_WINDOW, min_periods=min_history).quantile(enter_quantile)
    lo = smoothed.rolling(HYSTERESIS_WINDOW, min_periods=min_history).quantile(exit_quantile)
    state = 0.0
    out: list[float] = []
    for value, enter, exit_ in zip(smoothed.to_numpy(), hi.to_numpy(), lo.to_numpy()):
        if np.isnan(enter) or np.isnan(value):
            state = 0.0
        elif state == 0.0 and value > enter:
            state = 1.0
        elif state == 1.0 and value < exit_:
            state = 0.0
        out.append(state)
    return pd.Series(out, index=s.index, dtype="float64")


def _base_features(close: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Trailing, purely backward-looking per-symbol features."""
    ret = close.pct_change(fill_method=None)
    return {
        "ret_1": ret,
        "ret_5": close / close.shift(5) - 1.0,
        "ret_20": close / close.shift(20) - 1.0,
        "ret_60": close / close.shift(60) - 1.0,
        "vol_20": ret.rolling(VOL_WINDOW).std(ddof=0),
        "ma20_dist": close / close.rolling(20).mean() - 1.0,
        "ma60_dist": close / close.rolling(60).mean() - 1.0,
    }


def build_features(
    panel: dict[str, pd.DataFrame],
    *,
    registry=None,
    factor_ids: list[str] | None = None,
) -> pd.DataFrame:
    """Long feature frame indexed by (date, symbol); one column per feature.

    Includes trailing price features, raw ``tsmom``/``xsmom`` values, and the
    qlib158 momentum factors. Factor failures are skipped, never guessed.
    """
    close = panel.get("close")
    if close is None or close.empty:
        return pd.DataFrame()

    from arthaai.factors.momentum import trailing_return

    wide: dict[str, pd.DataFrame] = _base_features(close)
    tr126 = trailing_return(close, 126)
    wide["tsmom_126"] = (tr126 > 0).astype(float).where(tr126.notna())
    wide["xsmom_rank"] = tr126.rank(axis=1, ascending=False, method="first")
    wide["xsmom_126"] = tr126

    ids = factor_ids if factor_ids is not None else ZOO_FACTOR_IDS
    if ids:
        if registry is None:
            from arthaai.factors.registry import get_default_registry

            registry = get_default_registry()
        for fid in ids:
            try:
                factor = registry.compute(fid, panel)
            except Exception:  # noqa: BLE001, S112 - a missing factor must not kill the model
                continue
            if factor is not None and not factor.empty:
                wide[fid] = factor.reindex(index=close.index, columns=close.columns)

    frames = []
    for name, frame in wide.items():
        long = frame.stack().rename(name)
        frames.append(long)
    if not frames:
        return pd.DataFrame()
    features = pd.concat(frames, axis=1)
    features.index.names = ["date", "symbol"]
    classes = pd.Series(
        {sym: asset_class(sym) for sym in close.columns}, name="asset_class"
    )
    features["asset_class"] = features.index.get_level_values("symbol").map(classes)
    features["asset_class"] = features["asset_class"].astype("category")
    return features


def walk_forward_scores(
    features: pd.DataFrame,
    target: pd.Series,
    *,
    params: dict | None = None,
    initial_train_frac: float = INITIAL_TRAIN_FRAC,
    step_frac: float = STEP_FRAC,
) -> pd.Series:
    """Expanding-window XGBoost fit/predict over time; returns raw score per row.

    Features and target share a ``(date, symbol)`` MultiIndex. The model is fit on
    all rows up to a date cutoff and predicts the next slice; the cutoff expands by
    ``step_frac`` each step. No OOS tuning.
    """
    try:
        import xgboost as xgb
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "xgb_zoo requires the optional 'ml' extra: pip install -e '.[ml]'"
        ) from exc

    params = dict(XGB_PARAMS if params is None else params)
    joined = features.join(target.rename("target")).dropna(subset=["target"])
    if joined.empty:
        return pd.Series(dtype="float64")

    design = joined.drop(columns="target")
    y = joined["target"]
    dates = joined.index.get_level_values("date")
    unique_dates = pd.DatetimeIndex(sorted(dates.unique()))
    if len(unique_dates) < 10:
        return pd.Series(dtype="float64")

    n = len(unique_dates)
    start = max(1, int(n * initial_train_frac))
    step = max(1, int(n * step_frac))
    scores = pd.Series(np.nan, index=joined.index, dtype="float64")
    for cutoff in range(start, n, step):
        train_end = unique_dates[cutoff - 1]
        test_end = unique_dates[min(cutoff + step, n) - 1]
        train_mask = dates <= train_end
        test_mask = (dates > train_end) & (dates <= test_end)
        if not train_mask.any() or not test_mask.any():
            continue
        model = xgb.XGBRegressor(**params)
        model.fit(design[train_mask], y[train_mask], verbose=False)
        scores[test_mask] = model.predict(design[test_mask])
    return scores


def xgb_signal_map(
    symbols: list[str],
    *,
    limit: int = 520,
    panel: dict[str, pd.DataFrame] | None = None,
    features: pd.DataFrame | None = None,
) -> dict[str, pd.Series]:
    """Build per-symbol causal ``xgb_zoo`` position series from a universe panel.

    Like the other cross-sectional signals (``xsmom``/``value``) this needs the full
    universe to rank against, so even a single-symbol request builds the whole panel
    and fits XGBoost over it. That fit is far heavier than the vectorized signals —
    pass an explicit ``panel``/``features`` to reuse work across repeated calls.
    """
    if panel is None:
        from arthaai.factors.panel import build_panel_from_symbols

        panel = build_panel_from_symbols(list(symbols), limit=limit)
    close = panel.get("close")
    if close is None or close.empty:
        return {}
    if features is None:
        features = build_features(panel)
    if features.empty:
        return {}
    target = vol_adjusted_forward_return(close).stack()
    target.index.names = ["date", "symbol"]
    scores = walk_forward_scores(features, target)
    if scores.empty:
        return {}

    out: dict[str, pd.Series] = {}
    for sym in close.columns:
        try:
            sym_scores = scores.xs(str(sym), level="symbol")
        except KeyError:
            continue
        positions = hysteresis_positions(sym_scores)
        out[str(sym)] = positions.dropna()
    return out
