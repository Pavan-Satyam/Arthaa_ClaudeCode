"""Free exogenous E3 axes — point-in-time alignment and signal maps (offline)."""

import numpy as np
import pandas as pd
import pytest

from arthaai.data import cftc, form4, pit, vix
from arthaai.factors.exogenous import (
    cftc_signal_map,
    eia_signal_map,
    insider_signal_map,
    vix_regime_signal_map,
)


def _dates(n=40, start="2024-01-01"):
    return pd.date_range(start, periods=n, freq="D", tz="UTC")


def _patch_panel(monkeypatch, symbols, dates):
    close = pd.DataFrame(
        {s: np.linspace(10.0, 20.0, len(dates)) for s in symbols}, index=dates
    )
    monkeypatch.setattr(
        "arthaai.factors.panel.build_panel_from_symbols",
        lambda syms, limit=520: {"close": close},
    )
    return close


# --- pit helpers ---------------------------------------------------------------

def test_release_lag_shift_business_days_skips_weekend():
    # Tuesday 2024-01-09 + 3 business days -> Friday 2024-01-12
    out = pit.release_lag_shift(["2024-01-09"], business_days=3)
    assert out[0] == pd.Timestamp("2024-01-12", tz="UTC")


def test_release_lag_shift_calendar_days():
    # Friday 2024-01-05 + 5 calendar days -> Wednesday 2024-01-10
    out = pit.release_lag_shift(["2024-01-05"], calendar_days=5)
    assert out[0] == pd.Timestamp("2024-01-10", tz="UTC")


def test_asof_align_is_backward_only():
    series = pd.Series(
        [1.0, 2.0], index=pd.to_datetime(["2024-01-05", "2024-01-10"], utc=True)
    )
    dates = pd.to_datetime(
        ["2024-01-04", "2024-01-05", "2024-01-08", "2024-01-10"], utc=True
    )
    aligned = pit.asof_align(series, dates)
    assert np.isnan(aligned.iloc[0])  # before any release
    assert aligned.iloc[1] == 1.0
    assert aligned.iloc[2] == 1.0  # carried forward, not peeked ahead
    assert aligned.iloc[3] == 2.0


def test_effective_dates_are_public_guard():
    ref = pd.to_datetime(["2024-01-09"], utc=True)
    eff = pit.release_lag_shift(ref, business_days=3)
    assert pit.effective_dates_are_public(ref, eff, min_business_days=3)
    with pytest.raises(ValueError):
        # no lag applied: effective == reference violates the required +3 lag
        pit.effective_dates_are_public(ref, ref, min_business_days=3)


# --- CFTC ----------------------------------------------------------------------

def test_cftc_net_noncommercial_and_effective_shift():
    frame = pd.DataFrame(
        {
            "report_date_as_yyyy_mm_dd": ["2024-01-09", "2024-01-16"],
            "noncomm_positions_long_all": [100, 120],
            "noncomm_positions_short_all": [40, 50],
        }
    )
    net = cftc.net_noncommercial(frame)
    assert net.tolist() == [60.0, 70.0]
    eff = cftc.to_effective(net)
    # Tue 01-09 -> Fri 01-12 ; Tue 01-16 -> Fri 01-19
    assert eff.index[0] == pd.Timestamp("2024-01-12", tz="UTC")
    assert eff.index[1] == pd.Timestamp("2024-01-19", tz="UTC")


def test_cftc_signal_map_covers_only_mapped_symbols(monkeypatch):
    dates = _dates()
    _patch_panel(monkeypatch, ["GLD", "SLV", "USO", "AAPL"], dates)
    cot = {"GLD": pd.Series(np.linspace(-5.0, 5.0, len(dates)), index=dates)}
    out = cftc_signal_map(["GLD", "SLV", "USO", "AAPL"], limit=100, cot=cot, z_window=5)
    assert "GLD" in out
    assert "AAPL" not in out
    assert set(out["GLD"].unique()) <= {0.0, 1.0}


# --- EIA -----------------------------------------------------------------------

def test_eia_signal_map_only_energy_names(monkeypatch):
    dates = _dates()
    _patch_panel(monkeypatch, ["USO", "XOM", "GLD"], dates)
    inventory = pd.Series(np.linspace(500.0, 400.0, len(dates)), index=dates)
    out = eia_signal_map(["USO", "XOM", "GLD"], limit=100, inventory=inventory, change_window=4)
    assert "USO" in out and "XOM" in out and "GLD" not in out


# --- Form 4 --------------------------------------------------------------------

def test_form4_anchors_on_filing_date_not_transaction_date():
    frame = pd.DataFrame(
        {
            "filing_date": ["2024-03-01", "2024-03-01"],
            "transaction_date": ["2024-02-20", "2024-02-20"],
            "transaction_code": ["P", "S"],
            "shares": [100, 30],
            "acquired_disposed": [None, None],
        }
    )
    series = form4.insider_net_buy(frame)
    assert series.index[0] == pd.Timestamp("2024-03-01", tz="UTC")
    assert series.iloc[0] == 70.0  # +100 buy, -30 sale


def test_form4_late_acceptance_pushes_to_next_business_day():
    eff = form4.effective_from_filing(["2024-03-01T17:00:00Z"])  # Friday after 16:00 ET
    assert eff[0] == pd.Timestamp("2024-03-04", tz="UTC")  # -> Monday


def test_form4_gift_code_is_neutral():
    frame = pd.DataFrame(
        {
            "filing_date": ["2024-03-01", "2024-03-01"],
            "transaction_code": ["P", "G"],
            "shares": [100, 50],
            "acquired_disposed": [None, None],
        }
    )
    series = form4.insider_net_buy(frame)
    assert series.iloc[0] == 100.0  # gift contributes 0; only the purchase counts


def test_form4_drops_unusable_shares_without_misaligning_dates():
    frame = pd.DataFrame(
        {
            "filing_date": ["2024-03-01", "2024-03-04"],
            "transaction_code": ["P", "S"],
            "shares": [100, None],
            "acquired_disposed": [None, None],
        }
    )
    series = form4.insider_net_buy(frame)
    assert series.index.tolist() == [pd.Timestamp("2024-03-01", tz="UTC")]
    assert series.iloc[0] == 100.0


def test_form4_fetch_caches_and_reuses_processor(monkeypatch, tmp_path):
    from arthaai.data import form4

    monkeypatch.setattr(form4, "_CACHE", tmp_path)
    calls = {"n": 0}

    class StubProcessor:
        def get_insider_trades(self, ticker, *, limit=100):
            calls["n"] += 1
            return pd.DataFrame(
                {
                    "filing_date": ["2024-03-01"],
                    "transaction_code": ["P"],
                    "shares": [10],
                    "acquired_disposed": [None],
                }
            )

    proc = StubProcessor()
    form4.fetch_insider_trades("AAA", processor=proc)
    second = form4.fetch_insider_trades("AAA", processor=proc)  # served from cache
    assert calls["n"] == 1  # no second network/processor call
    assert "filing_date" in second.columns


def test_events_to_sessions_maps_to_next_session_and_sums():
    from arthaai.factors.exogenous import _events_to_sessions

    sessions = pd.DatetimeIndex(
        pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"], utc=True)
    )
    two_filings = pd.Series(
        [5.0, 3.0], index=pd.to_datetime(["2024-01-02", "2024-01-02"], utc=True)
    )
    out = _events_to_sessions(two_filings, sessions)
    assert out.iloc[0] == 8.0  # both filings land on the first session, counted once
    assert np.isnan(out.iloc[1]) and np.isnan(out.iloc[2])


def test_events_to_sessions_maps_weekend_filing_forward():
    from arthaai.factors.exogenous import _events_to_sessions

    sessions = pd.DatetimeIndex(pd.to_datetime(["2024-01-05", "2024-01-08"], utc=True))
    saturday = pd.Series([7.0], index=pd.to_datetime(["2024-01-06"], utc=True))
    out = _events_to_sessions(saturday, sessions)
    assert np.isnan(out.iloc[0])  # Friday: not yet public
    assert out.iloc[1] == 7.0  # Monday: first session on/after


def test_insider_signal_map_cross_sectional(monkeypatch):
    dates = _dates()
    _patch_panel(monkeypatch, ["AAA", "BBB", "CCC"], dates)
    insider = {
        "AAA": pd.Series(10.0, index=dates),
        "BBB": pd.Series(1.0, index=dates),
        "CCC": pd.Series(0.0, index=dates),
    }
    out = insider_signal_map(["AAA", "BBB", "CCC"], limit=100, insider=insider, top_quantile=0.30)
    assert set(out) == {"AAA", "BBB", "CCC"}
    # AAA has the largest insider flow -> selected long on the last date
    assert out["AAA"].iloc[-1] == 1.0


# --- VIX -----------------------------------------------------------------------

def test_vix_parse_and_term_structure():
    csv = "DATE,OPEN,HIGH,LOW,CLOSE\n2024-01-02,13,15,12,14\n2024-01-03,14,16,13,15\n"
    s = vix.parse_cboe_csv(csv)
    assert s.tolist() == [14.0, 15.0]
    ratio = vix.term_structure_ratio(s, s * 2)
    assert ratio.tolist() == pytest.approx([0.5, 0.5])


def test_vix_regime_signal_map_calms_all_symbols(monkeypatch):
    dates = _dates()
    _patch_panel(monkeypatch, ["GLD", "AAPL"], dates)
    ratio = pd.Series(0.9, index=dates)  # contango -> calm -> long
    out = vix_regime_signal_map(["GLD", "AAPL"], limit=100, ratio=ratio)
    assert set(out) == {"GLD", "AAPL"}
    assert out["GLD"].iloc[-1] == 1.0
