"""Live news ingestion — RSS/Atom feeds into the Qdrant narrative store (ARTHA-216).

The News_Agent reads from Qdrant, but until now the only way to populate it was
the one-shot illustrative ``seed_news`` script. This module pulls real headlines
from RSS/Atom feeds, scores them deterministically, and upserts them as
source-attributed documents the hybrid search can retrieve.

Parsing uses the standard library (``xml.etree``) so no feed parser dependency is
required; fetching uses ``httpx``, already a core dependency. Sentiment is a small
lexicon score — deterministic and offline — standing in for the embedding-based
scorer until a scored feed is wired in.
"""

from __future__ import annotations

import hashlib
import ipaddress
import socket
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

from arthaai.db import qdrant

# Cap the feed body we are willing to buffer, and refuse redirects so a feed
# cannot bounce the server to an internal address.
MAX_FEED_BYTES = 5_000_000
_ALLOWED_SCHEMES = {"http", "https"}
_DENY_FLAGS = (
    "is_private", "is_loopback", "is_link_local", "is_reserved",
    "is_multicast", "is_unspecified",
)

_BULLISH = {
    "beat", "beats", "surge", "surges", "rally", "rallies", "gain", "gains",
    "record", "upgrade", "upgrades", "strong", "robust", "growth", "raises",
    "raised", "bullish", "outperform", "demand", "buyback", "upside", "soars",
}
_BEARISH = {
    "miss", "misses", "plunge", "plunges", "slump", "slumps", "fall", "falls",
    "downgrade", "downgrades", "weak", "warning", "warns", "cuts", "cut",
    "bearish", "underperform", "lawsuit", "probe", "recall", "default", "crash",
}

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


@dataclass
class FeedItem:
    headline: str
    summary: str
    source: str
    link: str = ""
    published: str = ""


def score_sentiment(text: str) -> float:
    """Deterministic lexicon sentiment in ``[-1, 1]``.

    Positive minus negative keyword counts, normalised by the total hits so a
    long article doesn't dominate a short one. No hits -> neutral (0.0).
    """
    tokens = {t.strip(".,:;!?()[]{}\"'").lower() for t in text.split()}
    pos = len(tokens & _BULLISH)
    neg = len(tokens & _BEARISH)
    if pos + neg == 0:
        return 0.0
    return round((pos - neg) / (pos + neg), 3)


def _text(element: ET.Element | None) -> str:
    if element is None or element.text is None:
        return ""
    return element.text.strip()


def parse_feed(xml_text: str, source: str = "feed") -> list[FeedItem]:
    """Parse RSS 2.0 or Atom XML into feed items.

    Supports the common shapes only; entries missing a title are skipped.
    """
    root = ET.fromstring(xml_text)
    items: list[FeedItem] = []

    # RSS 2.0: channel/item
    for item in root.iter("item"):
        headline = _text(item.find("title"))
        if not headline:
            continue
        items.append(FeedItem(
            headline=headline,
            summary=_text(item.find("description")),
            source=source,
            link=_text(item.find("link")),
            published=_text(item.find("pubDate")),
        ))

    # Atom: feed/entry
    for entry in root.iter(f"{_ATOM_NS}entry"):
        headline = _text(entry.find(f"{_ATOM_NS}title"))
        if not headline:
            continue
        link_el = entry.find(f"{_ATOM_NS}link")
        items.append(FeedItem(
            headline=headline,
            summary=_text(entry.find(f"{_ATOM_NS}summary"))
            or _text(entry.find(f"{_ATOM_NS}content")),
            source=source,
            link=(link_el.get("href", "") if link_el is not None else ""),
            published=_text(entry.find(f"{_ATOM_NS}updated")),
        ))

    return items


def _host_is_public(host: str) -> bool:
    """True only when every resolved address is a public (non-internal) IP."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if any(getattr(addr, flag) for flag in _DENY_FLAGS):
            return False
    return True


def is_allowed_feed_url(url: str) -> bool:
    """Reject non-http(s) schemes and hosts that resolve to internal addresses.

    Guards against SSRF: feeds are operator-supplied, but a malicious feed or a
    redirect could otherwise target loopback, RFC1918, or cloud-metadata IPs.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        return False
    return _host_is_public(parsed.hostname)


def fetch_feed(url: str, source: str = "", timeout: float = 10.0) -> list[FeedItem]:
    """Fetch and parse one feed URL. Network/parse/validation failures return ``[]``."""
    if not is_allowed_feed_url(url):
        return []
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=False)
        resp.raise_for_status()
    except Exception:  # noqa: BLE001 - a dead feed must not break ingestion
        return []
    if len(resp.content) > MAX_FEED_BYTES:
        return []
    return parse_feed(resp.text, source=source or url)


def _point_id(ticker: str, headline: str) -> int:
    """Stable positive 63-bit id from (ticker, headline) for idempotent upserts."""
    digest = hashlib.sha256(f"{ticker}:{headline}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def ingest_news(
    symbol: str,
    feeds: list[str],
    *,
    limit_per_feed: int = 10,
    source_names: dict[str, str] | None = None,
) -> int:
    """Fetch feeds, score items, and upsert them for ``symbol`` into Qdrant.

    Returns the number of documents upserted. Re-running is idempotent: point ids
    are derived from (ticker, headline).
    """
    symbol = symbol.upper()
    source_names = source_names or {}
    docs: list[dict] = []
    seen: set[str] = set()
    for url in feeds:
        items = fetch_feed(url, source=source_names.get(url, ""))
        for item in items[:limit_per_feed]:
            if item.headline in seen:
                continue
            seen.add(item.headline)
            text = f"{item.headline} {item.summary}"
            docs.append({
                "id": _point_id(symbol, item.headline),
                "ticker": symbol,
                "source": item.source,
                "sentiment": score_sentiment(text),
                "headline": item.headline,
                "ts": item.published or None,
            })
    if not docs:
        return 0
    return qdrant.upsert_news(docs)