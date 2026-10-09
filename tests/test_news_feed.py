"""Live news ingestion — feed parsing, sentiment, Qdrant upsert (ARTHA-216)."""

from arthaai.data import news_feed

_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Gold surges as safe-haven demand beats expectations</title>
    <description>Bullish flows lift the metal.</description>
    <link>https://example.com/a</link>
    <pubDate>Mon, 01 Jan 2024 00:00:00 GMT</pubDate>
  </item>
  <item>
    <title>Oil plunges on weak demand and a downgrade</title>
    <description>Bearish inventory data.</description>
  </item>
</channel></rss>"""

_ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Apple beats estimates</title>
    <summary>Record services growth.</summary>
    <link href="https://example.com/b"/>
    <updated>2024-01-01T00:00:00Z</updated>
  </entry>
</feed>"""


class TestParse:
    def test_parses_rss_items(self):
        items = news_feed.parse_feed(_RSS, source="TestFeed")
        assert len(items) == 2
        assert items[0].headline.startswith("Gold surges")
        assert items[0].source == "TestFeed"
        assert items[0].link == "https://example.com/a"
        assert items[0].published.startswith("Mon,")

    def test_parses_atom_entries(self):
        items = news_feed.parse_feed(_ATOM, source="AtomFeed")
        assert len(items) == 1
        assert items[0].headline == "Apple beats estimates"
        assert items[0].link == "https://example.com/b"

    def test_skips_entries_without_title(self):
        xml = "<rss><channel><item><description>no title</description></item></channel></rss>"
        assert news_feed.parse_feed(xml) == []


class TestUrlValidation:
    def test_rejects_non_http_scheme(self):
        assert news_feed.is_allowed_feed_url("ftp://example.com/feed") is False

    def test_rejects_empty(self):
        assert news_feed.is_allowed_feed_url("") is False

    def test_rejects_loopback(self):
        assert news_feed.is_allowed_feed_url("http://127.0.0.1/feed") is False

    def test_rejects_private_range(self):
        assert news_feed.is_allowed_feed_url("http://10.0.0.1/feed") is False

    def test_rejects_cloud_metadata(self):
        assert news_feed.is_allowed_feed_url("http://169.254.169.254/latest/meta-data") is False

    def test_fetch_does_not_call_http_for_disallowed_url(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("httpx.get must not be called for a disallowed URL")

        monkeypatch.setattr(news_feed.httpx, "get", boom)
        assert news_feed.fetch_feed("http://169.254.169.254/") == []


class TestSentiment:
    def test_bullish_text_is_positive(self):
        assert news_feed.score_sentiment("Gold surges and beats expectations") > 0

    def test_bearish_text_is_negative(self):
        assert news_feed.score_sentiment("Oil plunges on weak demand and downgrade") < 0

    def test_neutral_text_is_zero(self):
        assert news_feed.score_sentiment("The committee met on Tuesday") == 0.0


class TestIngest:
    def test_ingest_upserts_scored_docs(self, monkeypatch):
        captured = {}

        def fake_upsert(docs):
            captured["docs"] = docs
            return len(docs)

        monkeypatch.setattr(news_feed, "fetch_feed", lambda url, source="": news_feed.parse_feed(_RSS, source))
        monkeypatch.setattr(news_feed.qdrant, "upsert_news", fake_upsert)

        n = news_feed.ingest_news("GLD", ["https://feed"], limit_per_feed=10)
        assert n == 2
        docs = captured["docs"]
        assert all(d["ticker"] == "GLD" for d in docs)
        assert docs[0]["sentiment"] > 0
        assert docs[1]["sentiment"] < 0

    def test_ids_are_stable_across_runs(self, monkeypatch):
        monkeypatch.setattr(news_feed, "fetch_feed", lambda url, source="": news_feed.parse_feed(_RSS, source))
        seen = []
        monkeypatch.setattr(news_feed.qdrant, "upsert_news", lambda docs: seen.append(docs) or len(docs))
        news_feed.ingest_news("GLD", ["https://feed"])
        news_feed.ingest_news("GLD", ["https://feed"])
        assert seen[0][0]["id"] == seen[1][0]["id"]

    def test_empty_feeds_upsert_nothing(self, monkeypatch):
        monkeypatch.setattr(news_feed, "fetch_feed", lambda url, source="": [])
        monkeypatch.setattr(news_feed.qdrant, "upsert_news", lambda docs: len(docs))
        assert news_feed.ingest_news("GLD", ["https://feed"]) == 0