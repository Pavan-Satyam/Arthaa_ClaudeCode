"""RSS article ingestion and optional local FinBERT sentiment scoring."""

from __future__ import annotations

import logging
from typing import Any, ClassVar, TypedDict

import httpx

from arthaai.data.news_feed import is_allowed_feed_url


class NewsArticle(TypedDict):
    source: str
    title: str
    url: str
    published: str
    summary: str


class SentimentResult(TypedDict):
    label: str
    score: float
    probabilities: dict[str, float]


class NewsSentimentAnalyzer:
    """Fetch public RSS content safely and classify text with FinBERT on demand."""

    MODEL_NAME = "ProsusAI/finbert"
    DEFAULT_FEEDS: ClassVar[dict[str, str]] = {
        "pr_news_wire": "https://www.prnewswire.com/rss/news-releases-list.rss",
        "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
    }

    def __init__(self, classifier: Any | None = None, timeout: float = 12.0) -> None:
        self._classifier = classifier
        self._timeout = timeout
        self._logger = logging.getLogger("arthaai.news_sentiment")

    def fetch_rss(self, feeds: dict[str, str] | None = None) -> list[NewsArticle]:
        """Fetch named RSS/Atom URLs; reject private hosts and redirects."""
        try:
            import feedparser
        except ImportError as exc:
            raise RuntimeError("RSS support requires `pip install -e '.[news]'`.") from exc

        articles: list[NewsArticle] = []
        for source, url in (feeds or self.DEFAULT_FEEDS).items():
            if not is_allowed_feed_url(url):
                continue
            try:
                response = httpx.get(url, timeout=self._timeout, follow_redirects=False)
                response.raise_for_status()
                if len(response.content) > 5_000_000:
                    continue
                parsed = feedparser.parse(response.content)
            except Exception as exc:  # noqa: BLE001 - a dead feed must not block other sources
                self._logger.warning("news_feed_failed", extra={"source": source, "error": str(exc)})
                continue
            for entry in parsed.entries:
                articles.append(
                    NewsArticle(
                        source=source,
                        title=str(entry.get("title", "")),
                        url=str(entry.get("link", "")),
                        published=str(entry.get("published", entry.get("updated", ""))),
                        summary=str(entry.get("summary", "")),
                    )
                )
        return articles

    def scrape_article(self, url: str) -> str:
        """Extract clean Markdown from a public article URL without following redirects."""
        if not is_allowed_feed_url(url):
            raise ValueError("article URL must use HTTP(S) and resolve to a public host")
        try:
            import trafilatura
        except ImportError as exc:
            raise RuntimeError("Article extraction requires `pip install -e '.[news]'`.") from exc
        response = httpx.get(url, timeout=self._timeout, follow_redirects=False)
        response.raise_for_status()
        text = trafilatura.extract(response.text, output_format="markdown", include_comments=False)
        return text or ""

    def _get_classifier(self):
        if self._classifier is None:
            try:
                from transformers import pipeline
            except ImportError as exc:
                raise RuntimeError("FinBERT requires `pip install -e '.[sentiment]'`.") from exc
            self._classifier = pipeline(
                "text-classification", model=self.MODEL_NAME, top_k=None
            )
        return self._classifier

    def score_sentiment(self, article_text: str) -> SentimentResult:
        """Return FinBERT positive/negative/neutral probabilities and top label."""
        text = article_text.strip()
        if not text:
            raise ValueError("article_text must not be empty")
        raw = self._get_classifier()(text[:20_000], truncation=True)
        if raw and isinstance(raw[0], list):
            raw = raw[0]
        probabilities = {str(item["label"]).lower(): float(item["score"]) for item in raw}
        normalized = {label: probabilities.get(label, 0.0) for label in ("positive", "negative", "neutral")}
        label = max(normalized, key=normalized.get)
        return SentimentResult(
            label=label.capitalize(),
            score=normalized[label],
            probabilities=normalized,
        )