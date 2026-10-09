"""Cross-sectional factor composite — standardisation, averaging, ranking (ARTHA-219)."""

import numpy as np
import pandas as pd
import pytest

from arthaai.factors import composite


def _dates(n=3):
    return pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")


class TestZScore:
    def test_row_standardised_across_symbols(self):
        df = pd.DataFrame([[1.0, 2.0, 3.0]], index=_dates(1), columns=["A", "B", "C"])
        z = composite.cross_sectional_zscore(df)
        assert z.iloc[0]["B"] == pytest.approx(0.0)
        assert z.iloc[0]["A"] == pytest.approx(-1.0)
        assert z.iloc[0]["C"] == pytest.approx(1.0)

    def test_zero_dispersion_is_nan(self):
        df = pd.DataFrame([[5.0, 5.0]], index=_dates(1), columns=["A", "B"])
        assert composite.cross_sectional_zscore(df).isna().all().all()

    def test_empty_frame(self):
        assert composite.cross_sectional_zscore(pd.DataFrame()).empty


class TestCompositeScores:
    def test_averages_aligned_factors(self):
        idx = _dates(1)
        f1 = pd.DataFrame([[1.0, 2.0, 3.0]], index=idx, columns=["A", "B", "C"])
        f2 = pd.DataFrame([[1.0, 3.0, 2.0]], index=idx, columns=["A", "B", "C"])
        comp = composite.composite_scores({"f1": f1, "f2": f2})
        # A is lowest in both -> most negative; B is highest in f1, mid in f2.
        assert comp.iloc[0]["A"] < comp.iloc[0]["C"]
        assert set(comp.columns) == {"A", "B", "C"}

    def test_min_assets_drops_thin_dates(self):
        idx = _dates(2)
        f = pd.DataFrame(
            [[1.0, 2.0, np.nan], [1.0, np.nan, np.nan]], index=idx, columns=["A", "B", "C"]
        )
        comp = composite.composite_scores({"f": f}, min_assets=2)
        assert comp.iloc[0].notna().sum() == 2
        assert comp.iloc[1].isna().all()

    def test_no_factors_is_empty(self):
        assert composite.composite_scores({}).empty


class TestRanking:
    def _comp(self):
        idx = _dates(2)
        return pd.DataFrame(
            [[0.5, -1.0, 2.0], [1.0, 0.0, -0.5]], index=idx, columns=["A", "B", "C"]
        )

    def test_rank_orders_best_first(self):
        ranked = composite.rank_assets(self._comp())
        assert list(ranked.index) == ["A", "B", "C"]  # last row: A=1.0, B=0.0, C=-0.5

    def test_rank_at_specific_date(self):
        ranked = composite.rank_assets(self._comp(), date=_dates(2)[0])
        assert list(ranked.index) == ["C", "A", "B"]

    def test_rank_empty(self):
        assert composite.rank_assets(pd.DataFrame()).empty


class TestCompositeFromPanel:
    class _Registry:
        def compute(self, fid, panel):
            if fid == "boom":
                raise ValueError("bad factor")
            return panel["close"]

    def test_builds_from_panel_skipping_bad_factors(self):
        panel = {"close": pd.DataFrame([[1.0, 2.0, 3.0]], index=_dates(1), columns=["A", "B", "C"])}
        comp = composite.composite_from_panel(panel, ["boom", "ok"], registry=self._Registry())
        assert not comp.empty
        assert list(comp.columns) == ["A", "B", "C"]

    def test_empty_panel(self):
        assert composite.composite_from_panel({}, registry=self._Registry()).empty


class TestICWeightedComposite:
    def _panel(self, n=60, m=5):
        idx = pd.date_range("2024-01-01", periods=n, freq="B", tz="UTC")
        rng = np.random.default_rng(0)
        close = pd.DataFrame(100 + rng.normal(size=(n, m)).cumsum(axis=0),
                             index=idx, columns=[f"A{i}" for i in range(m)])
        return {"close": close, "high": close * 1.01, "low": close * 0.99,
                "open": close, "volume": 1e6}

    class _Reg:
        def compute(self, fid, panel):
            if fid == "up":
                return panel["close"]
            if fid == "down":
                return panel["close"].rank(axis=1)
            raise ValueError("bad factor")

    def test_returns_wide_frame(self):
        comp = composite.ic_weighted_composite(
            self._panel(), ["up", "down"], registry=self._Reg(), min_ic_obs=5
        )
        assert not comp.empty
        assert comp.shape[1] == 5

    def test_high_min_ic_falls_back_to_equal_weight(self):
        panel = self._panel()
        reg = self._Reg()
        comp = composite.ic_weighted_composite(
            panel, ["up", "down"], registry=reg, min_ic_obs=10 ** 9
        )
        expected = composite.composite_scores(
            {"up": reg.compute("up", panel), "down": reg.compute("down", panel)}
        ).reindex(index=comp.index, columns=comp.columns)
        diff = (comp.fillna(0.0) - expected.fillna(0.0)).abs().to_numpy().max()
        assert diff < 1e-9

    def test_bad_factor_is_skipped(self):
        comp = composite.ic_weighted_composite(
            self._panel(), ["up", "bad"], registry=self._Reg(), min_ic_obs=5
        )
        assert not comp.empty

    def test_empty_panel(self):
        assert composite.ic_weighted_composite({}, registry=self._Reg()).empty