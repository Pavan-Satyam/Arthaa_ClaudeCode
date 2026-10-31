"""XGBoost-over-factor-zoo harness — the pre-registered, DB-independent pieces."""

import numpy as np
import pandas as pd
import pytest

from arthaai.factors import xgb_signal


def _panel(n=200, symbols=("AAA", "GLD")):
    dates = pd.date_range("2022-01-03", periods=n, freq="B", tz="UTC")
    rng = np.random.default_rng(0)
    close = pd.DataFrame(
        {s: 100.0 * np.cumprod(1.0 + rng.normal(0.0, 0.01, n)) for s in symbols},
        index=dates,
    )
    return {"close": close}


def test_vol_adjusted_forward_return_scales_by_trailing_vol():
    panel = _panel()
    close = panel["close"]
    raw = close.shift(-1) / close - 1.0
    vol = close.pct_change(fill_method=None).rolling(20).std(ddof=0)
    expected = raw / vol
    got = xgb_signal.vol_adjusted_forward_return(close)
    pd.testing.assert_frame_equal(got, expected)


def test_hysteresis_never_positions_before_min_history():
    dates = pd.date_range("2022-01-03", periods=120, freq="B", tz="UTC")
    score = pd.Series(np.linspace(0.0, 5.0, 120), index=dates)
    pos = xgb_signal.hysteresis_positions(score, min_history=60)
    assert (pos.iloc[:59] == 0.0).all()  # flat until the 60th observation
    # a steadily rising score eventually enters long
    assert pos.iloc[-1] == 1.0


def test_hysteresis_is_causal_and_binary():
    dates = pd.date_range("2022-01-03", periods=150, freq="B", tz="UTC")
    rng = np.random.default_rng(1)
    score = pd.Series(rng.normal(0.0, 1.0, 150), index=dates)
    prefix = xgb_signal.hysteresis_positions(score.iloc[:100], min_history=30)
    full = xgb_signal.hysteresis_positions(score, min_history=30)
    # appending future data must not change past positions
    pd.testing.assert_series_equal(prefix, full.iloc[:100])
    assert set(full.unique()) <= {0.0, 1.0}


def test_build_features_are_backward_looking_and_classed():
    panel = _panel(symbols=("AAA", "GLD"))
    features = xgb_signal.build_features(panel, factor_ids=[])
    assert not features.empty
    assert "asset_class" in features.columns
    assert features.index.names == ["date", "symbol"]
    classes = features["asset_class"].astype(str).groupby(level="symbol").first()
    assert classes.loc["GLD"] == "commodity"
    assert classes.loc["AAA"] == "equity"
    # no composite/meta-signal columns leaked in
    assert not any("ic_composite" in str(c) for c in features.columns)


def test_walk_forward_scores_requires_ml_extra_when_xgboost_absent():
    try:
        import xgboost  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("xgboost installed; missing-extra path not exercised")
    features = pd.DataFrame({"f": [1.0]}, index=pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2022-01-03", tz="UTC"), "AAA")], names=["date", "symbol"]
    ))
    target = pd.Series([0.1], index=features.index)
    with pytest.raises(RuntimeError, match="ml"):
        xgb_signal.walk_forward_scores(features, target)
