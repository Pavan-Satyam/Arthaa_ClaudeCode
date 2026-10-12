"""Point-in-time universe membership (survivorship / selection-bias control).

A security is a universe member over the listing window ``[valid_from, valid_to)``;
``valid_to`` is ``None`` while the security is still listed. Membership comes from
a governed security master; absent a vendor it can be derived from observed OHLCV
coverage (first/last bar) as a conservative, point-in-time floor.

This does not by itself remove survivorship bias — that needs delisted-securities
history — but it provides the schema, the as-of query, and the ingestion interface
so a vendor can populate the same table without consumers changing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Membership:
    symbol: str
    valid_from: str
    valid_to: str | None
    source: str


def _as_date(value: Any) -> str:
    return str(value)[:10]


def derive_membership(
    coverage: list[dict], *, source: str = "ohlcv_coverage"
) -> list[Membership]:
    """Derive a listing window per symbol from bar coverage (first/last bar date).

    ``valid_to`` is the last observed bar; for a still-listed security that is
    "as of now", so the window covers every historical date on which we actually
    have data. Symbols with no bars are skipped (no fabricated membership).
    """
    out: list[Membership] = []
    for row in coverage:
        symbol = str(row.get("symbol") or "").upper()
        first = row.get("first")
        if not symbol or not first:
            continue
        last = row.get("last")
        out.append(
            Membership(
                symbol=symbol,
                valid_from=_as_date(first),
                valid_to=_as_date(last) if last else None,
                source=source,
            )
        )
    return out


def members_as_of(
    rows: list[dict], as_of: Any, *, asset_class: str | None = None
) -> list[str]:
    """Symbols whose listing window covers ``as_of`` (date-only comparison).

    ``rows`` are membership dicts with ``symbol``/``valid_from``/``valid_to`` and
    optionally ``asset_class``. Pure function: no clock, no I/O.
    """
    target = _as_date(as_of)
    members: set[str] = set()
    for row in rows:
        if asset_class is not None and row.get("asset_class") not in (None, asset_class):
            continue
        start = row.get("valid_from")
        if not start or _as_date(start) > target:
            continue
        end = row.get("valid_to")
        if end is not None and _as_date(end) < target:
            continue
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            members.add(symbol)
    return sorted(members)
