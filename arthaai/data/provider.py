"""Multi-source ingestion failover chain.

Tries LSE (London Strategic Edge) first, falls back to yfinance when LSE
returns empty (symbol not available, e.g. USO) or errors. A single
``ingest_resilient()`` entry point means the user never needs to know which
provider has which symbol.

Provider chain (auto mode):
    1. LSE  — if API key set, returns empty DataFrame on 404
    2. yfinance — fallback for any symbol LSE doesn't have
    3. If both empty → symbol not found anywhere

Each provider's incremental ingest is preserved: ``latest_ts()`` is checked
before fetching so only new bars are downloaded.

Usage::

    from arthaai.data.provider import ingest_resilient
    rows, provider = ingest_resilient("GLD")
    print(f"ingested {rows} bars via {provider}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import pandas as pd

import arthaai.config
from arthaai.db import timescale

_log = logging.getLogger("arthaai.data.provider")
_OHLCV_COLUMNS = ["ts", "open", "high", "low", "close", "volume"]
_CUSTOM_PROVIDERS: dict[str, OHLCVProvider] = {}


class OHLCVProvider(Protocol):
    """Provider contract: return canonical ArthaAI OHLCV columns."""

    name: str
    adjustment_basis: str

    def is_available(self) -> bool: ...

    def fetch_ohlcv(
        self, symbol: str, start: datetime, end: datetime, timeframe: str
    ) -> pd.DataFrame: ...

    def provider_symbol(self, symbol: str) -> str: ...


class LSEProvider:
    """Adapter for the existing London Strategic Edge integration."""

    name = "lse"
    adjustment_basis = "provider_native_unspecified"

    def is_available(self) -> bool:
        return bool(arthaai.config.get_settings().lse_api_key)

    def fetch_ohlcv(
        self, symbol: str, start: datetime, end: datetime, timeframe: str
    ) -> pd.DataFrame:
        from arthaai.data import lse

        return lse.download(symbol, start, end, timeframe=timeframe)

    def provider_symbol(self, symbol: str) -> str:
        return symbol


class YFinanceProvider:
    """Adapter for the existing yfinance downloader."""

    name = "yfinance"
    adjustment_basis = "yfinance_auto_adjust_false"

    def is_available(self) -> bool:
        return True

    def fetch_ohlcv(
        self, symbol: str, start: datetime, end: datetime, timeframe: str
    ) -> pd.DataFrame:
        from arthaai.data import ingest as yf_ingest_mod

        interval = timeframe if timeframe in ("1d", "1h", "5m", "1m") else "1d"
        return yf_ingest_mod._download(symbol, start, interval)

    def provider_symbol(self, symbol: str) -> str:
        return symbol


class ProviderRegistry:
    """Ordered adapters used for auto fallback or an explicitly selected source."""

    def __init__(self, providers: list[OHLCVProvider]) -> None:
        names = [provider.name for provider in providers]
        if len(names) != len(set(names)):
            raise ValueError("provider names must be unique")
        self._providers = tuple(providers)
        self._by_name = {provider.name: provider for provider in providers}

    def has_provider(self, name: str) -> bool:
        return name in self._by_name

    def adjustment_basis(self, name: str) -> str | None:
        provider = self._by_name.get(name)
        return getattr(provider, "adjustment_basis", None) if provider else None

    def provider_symbol(self, name: str, symbol: str) -> str:
        provider = self._by_name.get(name)
        mapping = getattr(provider, "provider_symbol", None) if provider else None
        return str(mapping(symbol)) if callable(mapping) else symbol

    def fetch(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        timeframe: str,
        *,
        provider: str = "auto",
    ) -> tuple[pd.DataFrame, str]:
        if provider == "auto":
            candidates = [item for item in self._providers if item.is_available()]
        else:
            selected = self._by_name.get(provider)
            if selected is None:
                raise ValueError(f"unknown provider '{provider}'")
            if not selected.is_available():
                raise RuntimeError(f"market-data provider '{provider}' is not available")
            candidates = [selected]

        for adapter in candidates:
            try:
                frame = adapter.fetch_ohlcv(symbol, start, end, timeframe)
                if not frame.empty:
                    return frame, adapter.name
            except Exception as exc:
                if provider != "auto":
                    raise
                _log.warning(
                    "market_data_provider_failed",
                    extra={"provider": adapter.name, "symbol": symbol, "error": str(exc)},
                )
        return pd.DataFrame(columns=_OHLCV_COLUMNS), "none"


def default_provider_registry() -> ProviderRegistry:
    """Build LSE→Yahoo defaults followed by adapters registered by the host app."""
    return ProviderRegistry([LSEProvider(), YFinanceProvider(), *_CUSTOM_PROVIDERS.values()])


def register_provider(provider: OHLCVProvider) -> None:
    """Register a custom adapter for configuration-driven selection.

    Host applications register adapters during startup. Built-in names are
    reserved; duplicate custom names fail rather than silently changing routing.
    """
    name = provider.name.strip().lower()
    if not name or name == "auto":
        raise ValueError("provider name must be non-empty and cannot be 'auto'")
    if provider.name != name:
        raise ValueError("provider name must be lowercase with no surrounding whitespace")
    if name in {"lse", "yfinance"}:
        raise ValueError(f"provider name '{name}' is reserved")
    if name in _CUSTOM_PROVIDERS:
        raise ValueError(f"provider '{name}' is already registered")
    provider.name = name
    _CUSTOM_PROVIDERS[name] = provider


@dataclass
class IngestResult:
    """Outcome of a resilient ingest — how many bars and which provider succeeded."""

    rows: int
    provider: str  # "lse" | "yfinance" | "none"
    symbol: str
    incremental: bool  # True if only fetched new bars


def fetch_ohlcv(
    symbol: str,
    start: datetime,
    end: datetime,
    timeframe: str = "1d",
    *,
    provider: str = "auto",
    registry: ProviderRegistry | None = None,
) -> tuple[pd.DataFrame, str]:
    """Fetch canonical OHLCV through the registry; return frame and provider name.

    Auto mode preserves the current LSE-when-configured then yfinance order.
    A named provider bypasses auto selection and uses only that adapter.
    """
    symbol = symbol.upper()
    active_registry = registry or default_provider_registry()
    selected_provider = provider
    if provider == "auto":
        configured = getattr(arthaai.config.get_settings(), "market_data_provider", "auto")
        configured = str(configured).strip().lower() or "auto"
        if configured != "auto":
            if not active_registry.has_provider(configured):
                raise ValueError(
                    f"configured market-data provider '{configured}' is not registered"
                )
            selected_provider = configured
    return active_registry.fetch(
        symbol, start, end, timeframe, provider=selected_provider
    )


def refresh_history(
    symbol: str,
    *,
    lookback_days: int = 30,
    timeframe: str = "1d",
    provider: str = "auto",
    registry: ProviderRegistry | None = None,
) -> IngestResult:
    """Re-fetch a bounded recent history window and upsert bars in place.

    Unlike ``ingest_resilient``, this intentionally overlaps existing dates so
    missing or provider-corrected bars can be repaired. It is an explicit
    maintenance operation; ordinary ingestion remains incremental.
    """
    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    active_registry = registry or default_provider_registry()
    if provider not in ("auto", "lse", "yfinance") and not (
        active_registry.has_provider(provider)
    ):
        raise ValueError("provider must be auto, lse, or yfinance")
    if timeframe not in ("1d", "1h", "5m", "1m"):
        raise ValueError("timeframe must be one of 1d, 1h, 5m, or 1m")

    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("symbol must not be empty")
    now = datetime.now(UTC)
    start = now - timedelta(days=lookback_days)

    if not timescale.asset_meta(symbol):
        from arthaai.data import lse as lse_mod

        name, asset_class = lse_mod._friendly_meta(symbol)
        timescale.ensure_asset(symbol, name=name, asset_class=asset_class)

    rows, used = fetch_ohlcv(
        symbol, start, now, timeframe=timeframe, provider=provider, registry=active_registry
    )

    if rows.empty:
        _record_provider(symbol, used)
        return IngestResult(rows=0, provider=used, symbol=symbol, incremental=False)

    written = timescale.upsert_ohlcv(
        symbol,
        timeframe,
        rows,
        source_provider=used,
        adjustment_basis=active_registry.adjustment_basis(used),
        provider_symbol=active_registry.provider_symbol(used, symbol),
    )
    _record_provider(symbol, used)
    from arthaai.data import ingest as yf_ingest_mod

    yf_ingest_mod._publish_event(symbol, written)
    return IngestResult(rows=written, provider=used, symbol=symbol, incremental=False)


def refresh_history_batch(
    symbols: list[str],
    *,
    lookback_days: int = 30,
    timeframe: str = "1d",
    provider: str = "auto",
    registry: ProviderRegistry | None = None,
) -> list[IngestResult]:
    """Refresh a set of symbols sequentially, retaining failures per symbol.

    The complete input is validated before any provider or database call. A
    failure for one symbol is represented as ``provider='error'`` and does not
    prevent subsequent symbols from being refreshed.
    """
    normalized = [symbol.strip().upper() for symbol in symbols]
    if not normalized or any(not symbol for symbol in normalized):
        raise ValueError("symbols must contain at least one non-empty symbol")
    if len(set(normalized)) != len(normalized):
        raise ValueError("symbols must be unique (case-insensitive)")
    active_registry = registry or default_provider_registry()
    if lookback_days < 1:
        raise ValueError("lookback_days must be positive")
    if provider not in ("auto", "lse", "yfinance") and not (
        active_registry.has_provider(provider)
    ):
        raise ValueError("provider must be auto, lse, or yfinance")
    if timeframe not in ("1d", "1h", "5m", "1m"):
        raise ValueError("timeframe must be one of 1d, 1h, 5m, or 1m")

    results = []
    for symbol in normalized:
        try:
            results.append(
                refresh_history(
                    symbol,
                    lookback_days=lookback_days,
                    timeframe=timeframe,
                    provider=provider,
                    registry=active_registry,
                )
            )
        except Exception as exc:
            results.append(
                IngestResult(rows=0, provider="error", symbol=symbol, incremental=False)
            )
            import logging

            logging.getLogger("arthaai.data.provider").warning(
                "history_refresh_failed", extra={"symbol": symbol, "error": str(exc)}
            )
    return results


def _friendly_meta(symbol: str) -> tuple[str, str]:
    """Best-effort name + asset class — tries yfinance, falls back to LSE map."""
    from arthaai.data import ingest as yf_ingest_mod

    try:
        return yf_ingest_mod._friendly_meta(symbol)
    except Exception:
        from arthaai.data import lse as lse_mod

        return lse_mod._friendly_meta(symbol)


def _stored_preference(symbol: str) -> str | None:
    """Per-asset provider preference from the DB, or None.

    Best-effort: a database whose volume predates the provider columns must not
    break ingestion, so any DB error degrades to "no preference".
    """
    try:
        return timescale.get_preferred_provider(symbol)
    except Exception:
        return None


def _record_provider(symbol: str, used: str) -> None:
    """Record which provider served the last fetch. Best-effort (see above)."""
    try:
        timescale.record_ingest_provider(symbol, used)
    except Exception:
        pass


def ingest_resilient(
    symbol: str,
    lookback_days: int = 730,
    timeframe: str = "1d",
    provider: str = "auto",
    registry: ProviderRegistry | None = None,
) -> IngestResult:
    """Fetch OHLCV through the provider chain and persist to TimescaleDB.

    Args:
        symbol: Ticker symbol (e.g. "GLD", "USO", "AAPL").
        lookback_days: How far back to fetch if no existing data.
        timeframe: Candle timeframe — 1d, 1h, 5m, 1m.
        provider: "auto" (LSE → yfinance), "lse" (LSE only), "yfinance" (yfinance only).

    Returns:
        IngestResult with rows written, which provider succeeded, and whether
        the ingest was incremental (only new bars).
    """
    symbol = symbol.upper()

    # Ensure the asset exists (FK constraint)
    if not timescale.asset_meta(symbol):
        from arthaai.data import lse as lse_mod

        name, asset_class = lse_mod._friendly_meta(symbol)
        timescale.ensure_asset(symbol, name=name, asset_class=asset_class)

    # Incremental: check if we already have data
    last = timescale.latest_ts(symbol, timeframe)
    now = datetime.now(UTC)
    incremental = False

    if last:
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)
        if last.date() >= now.date():
            return IngestResult(rows=0, provider="none", symbol=symbol, incremental=True)
        start = last + timedelta(days=1)
        incremental = True
    else:
        start = now - timedelta(days=lookback_days)

    # Honour a stored per-asset preference when the caller didn't force a source.
    # (Set via `arthaai provider-status SYMBOL --prefer lse|yfinance`.)
    if provider == "auto":
        preference = _stored_preference(symbol)
        active_registry = registry or default_provider_registry()
        if preference and active_registry.has_provider(preference):
            provider = preference
    else:
        active_registry = registry or default_provider_registry()

    # Route to the appropriate provider
    df, used = fetch_ohlcv(
        symbol, start, now, timeframe=timeframe, provider=provider, registry=active_registry
    )

    if df.empty:
        _record_provider(symbol, used)
        return IngestResult(rows=0, provider=used, symbol=symbol, incremental=incremental)

    written = timescale.upsert_ohlcv(
        symbol,
        timeframe,
        df,
        source_provider=used,
        adjustment_basis=active_registry.adjustment_basis(used),
        provider_symbol=active_registry.provider_symbol(used, symbol),
    )
    _record_provider(symbol, used)

    # Publish Kafka event (best-effort, never blocks)
    try:
        from arthaai.data import ingest as yf_ingest_mod

        yf_ingest_mod._publish_event(symbol, written)
    except Exception:
        pass

    return IngestResult(rows=written, provider=used, symbol=symbol, incremental=incremental)
