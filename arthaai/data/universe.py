"""Dynamic universe loader — registers every US-listed symbol into `assets`.

Pulls the official NASDAQ Trader symbol directory (free, no key): all Nasdaq- and
other-exchange-listed securities. This is a *catalog* (symbol + name + type) — it
does NOT fetch price history. Prices are still ingested on demand per symbol when
you analyse one, so registering the whole market stays cheap (metadata only).

Bulk *price* backfill across the whole universe needs a paid bulk-data provider;
this loader deliberately does not attempt it.
"""

from __future__ import annotations

import httpx

from arthaai.db.timescale import connection

_NASDAQ = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
_OTHER = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


def _parse(text: str, symbol_col: str) -> list[tuple[str, str, str]]:
    lines = text.strip().splitlines()
    if not lines:
        return []
    header = lines[0].split("|")
    idx = {h: i for i, h in enumerate(header)}
    sym_i = idx.get(symbol_col)
    name_i = idx.get("Security Name")
    etf_i = idx.get("ETF")
    test_i = idx.get("Test Issue")
    if sym_i is None or name_i is None:
        return []
    rows: list[tuple[str, str, str]] = []
    for ln in lines[1:]:
        if ln.startswith("File Creation Time"):
            continue
        p = ln.split("|")
        if len(p) <= max(i for i in (sym_i, name_i) if i is not None):
            continue
        sym = p[sym_i].strip()
        if not sym or (test_i is not None and p[test_i].strip() == "Y"):
            continue
        # skip preferred/warrant/unit tickers with special chars — not price-analysable
        if any(c in sym for c in "$.^/ "):
            continue
        etf = etf_i is not None and p[etf_i].strip() == "Y"
        rows.append((sym.upper(), p[name_i].strip(), "etf" if etf else "equity"))
    return rows


def sync() -> int:
    """Fetch both directories and upsert into `assets`. Returns symbols processed."""
    catalog: list[tuple[str, str, str]] = []
    for url, col in ((_NASDAQ, "Symbol"), (_OTHER, "ACT Symbol")):
        resp = httpx.get(url, timeout=30.0)
        resp.raise_for_status()
        catalog += _parse(resp.text, col)

    with connection() as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO assets (symbol, name, asset_class) VALUES (%s, %s, %s) "
            "ON CONFLICT (symbol) DO NOTHING;",
            catalog,
        )
        conn.commit()
    return len(catalog)


def search(query: str, limit: int = 20) -> list[dict]:
    """Case-insensitive lookup over the catalog by symbol or name (for pickers)."""
    like = f"%{query.upper()}%"
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT symbol, name, asset_class FROM assets "
            "WHERE symbol LIKE %s OR upper(name) LIKE %s ORDER BY symbol LIMIT %s;",
            (like, like, limit),
        )
        return [dict(zip(("symbol", "name", "asset_class"), r)) for r in cur.fetchall()]


def count() -> int:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM assets;")
        return cur.fetchone()[0]
