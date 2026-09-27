"""Additional deterministic indicators (ARTHA-220): ATR, Bollinger, MACD, OBV, VWAP."""

import pandas as pd
import pytest

from arthaai.agents import indicators as ind


def _series(vals):
    return pd.Series([float(v) for v in vals])


class TestATR:
    def test_constant_range_equals_range(self):
        n = 20
        high = _series([10.0] * n)
        low = _series([8.0] * n)
        close = _series([9.0] * n)
        assert ind.atr(high, low, close, period=3) == pytest.approx(2.0)

    def test_none_when_too_short(self):
        assert ind.atr(_series([10, 10]), _series([8, 8]), _series([9, 9]), period=14) is None

    def test_true_range_uses_prev_close_gap(self):
        high = _series([10, 20])
        low = _series([9, 15])
        close = _series([9.5, 18])
        tr = ind.true_range(high, low, close)
        # bar 1: max(20-15, |20-9.5|, |15-9.5|) = 10.5
        assert tr.iloc[1] == pytest.approx(10.5)


class TestBollinger:
    def test_bands_ordered_around_mean(self):
        close = _series(range(1, 21))  # 1..20
        b = ind.bollinger(close, window=20, num_std=2.0)
        assert b is not None
        assert b["mid"] == pytest.approx(10.5)
        assert b["lower"] < b["mid"] < b["upper"]

    def test_none_when_too_short(self):
        assert ind.bollinger(_series([1, 2, 3]), window=20) is None


class TestMACD:
    def test_positive_on_uptrend(self):
        m = ind.macd(_series(range(1, 60)))
        assert m is not None
        assert m["macd"] > 0
        assert set(m) == {"macd", "signal", "hist"}
        assert m["hist"] == pytest.approx(m["macd"] - m["signal"])

    def test_none_when_too_short(self):
        assert ind.macd(_series(range(1, 10))) is None


class TestOBV:
    def test_accumulates_up_day_volume(self):
        close = _series([1, 2, 3, 4])          # 3 up days
        volume = _series([10, 10, 10, 10])
        assert ind.obv(close, volume) == pytest.approx(30.0)

    def test_subtracts_down_day_volume(self):
        close = _series([4, 3, 2, 1])          # 3 down days
        volume = _series([10, 10, 10, 10])
        assert ind.obv(close, volume) == pytest.approx(-30.0)


class TestVWAP:
    def test_constant_price_equals_price(self):
        n = 5
        assert ind.vwap(
            _series([10] * n), _series([10] * n), _series([10] * n), _series([1] * n)
        ) == pytest.approx(10.0)

    def test_none_when_no_volume(self):
        assert ind.vwap(_series([10]), _series([9]), _series([9.5]), _series([0])) is None

    def test_windowed_uses_only_tail(self):
        high = low = close = _series([1, 1, 100, 100])
        volume = _series([1, 1, 1, 1])
        assert ind.vwap(high, low, close, volume, window=2) == pytest.approx(100.0)
