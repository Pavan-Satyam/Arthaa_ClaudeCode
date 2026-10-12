"""Asset metadata enrichment for the security master (exchange, asset class).

The registered universe stores ``symbol``/``name``/``asset_class``/``exchange``,
but the ingest path historically never captured ``exchange`` (and left many
ETFs mislabeled as ``equity``). This module fetches and normalizes that metadata
from yfinance so the evaluation universe can be selected on real exchange
identity rather than a guessed default.

The fetch is injectable (``info_factory``) so tests never hit the network.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

_NASDAQ_CODES = {"NMS", "NGM", "NCM", "NAS", "NASDAQ"}


def normalize_exchange(code: str | None, full_name: str | None = None) -> str | None:
    """Normalize a yfinance exchange code/name to a canonical short label.

    ``fullExchangeName`` (e.g. "NasdaqGS", "NYSEArca") is preferred when present
    because the short code alone is ambiguous across venues.
    """
    name = (full_name or "").strip().lower()
    raw = (code or "").strip().upper()
    if name:
        if "nasdaq" in name:
            return "NASDAQ"
        if "arca" in name:
            return "NYSEARCA"
        if "american" in name or "amex" in name:
            return "NYSEAMERICAN"
        if "cboe" in name or "bats" in name:
            return "BATS"
        if "nyse" in name:
            return "NYSE"
    if raw in _NASDAQ_CODES:
        return "NASDAQ"
    if raw in {"PCX", "NYSEARCA"}:
        return "NYSEARCA"
    if raw in {"NYQ", "NYS", "NYSE"}:
        return "NYSE"
    if raw in {"ASE", "AMEX"}:
        return "NYSEAMERICAN"
    if raw in {"BTS", "BATS"}:
        return "BATS"
    return raw or None


def _default_info_factory(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    return yf.Ticker(symbol).info


def fetch_asset_metadata(
    symbol: str,
    *,
    info_factory: Callable[[str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return normalized ``name``/``asset_class``/``exchange``/``currency``.

    ``quoteType == "ETF"`` maps to ``asset_class="etf"``; anything else is
    ``equity``. Missing fields degrade to safe defaults rather than raising.
    """
    factory = info_factory or _default_info_factory
    info = factory(symbol) or {}
    name = info.get("shortName") or info.get("longName") or symbol
    quote = str(info.get("quoteType") or "").upper()
    return {
        "symbol": symbol.upper(),
        "name": name,
        "asset_class": "etf" if quote == "ETF" else "equity",
        "exchange": normalize_exchange(info.get("exchange"), info.get("fullExchangeName")),
        "currency": info.get("currency") or "USD",
    }
