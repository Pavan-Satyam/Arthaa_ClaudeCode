"""Prometheus metrics for the ArthaAI pipeline and gateway (ARTHA-508).

Optional dependency: if ``prometheus-client`` is not installed every handle
becomes a no-op, so instrumentation never becomes a hard requirement. Install
with the ``obs`` extra: ``pip install -e ".[obs]"``.
"""

from __future__ import annotations

try:  # optional
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Histogram,
        generate_latest,
    )

    _AVAILABLE = True
except Exception:  # noqa: BLE001 - metrics must never break the app
    _AVAILABLE = False


class _NoopMetric:
    """Mimics the prometheus metric surface and discards everything."""

    def labels(self, *args, **kwargs) -> "_NoopMetric":
        return self

    def inc(self, *args, **kwargs) -> None:
        return None

    def observe(self, *args, **kwargs) -> None:
        return None

    def set(self, *args, **kwargs) -> None:
        return None


if _AVAILABLE:
    HTTP_REQUESTS = Counter(
        "arthaai_http_requests_total", "Gateway HTTP requests.", ["method", "path", "status"]
    )
    HTTP_LATENCY = Histogram(
        "arthaai_http_request_seconds", "Gateway request latency.", ["method", "path"]
    )
    ANALYSES = Counter(
        "arthaai_analyses_total", "Pipeline analyses run.", ["symbol", "direction"]
    )
    PIPELINE_LATENCY = Histogram(
        "arthaai_pipeline_seconds", "End-to-end pipeline latency."
    )
    LLM_PROVIDER = Counter(
        "arthaai_llm_provider_total", "LLM verdicts by provider.", ["provider"]
    )
else:  # pragma: no cover - exercised only without the extra installed
    HTTP_REQUESTS = _NoopMetric()
    HTTP_LATENCY = _NoopMetric()
    ANALYSES = _NoopMetric()
    PIPELINE_LATENCY = _NoopMetric()
    LLM_PROVIDER = _NoopMetric()


def is_available() -> bool:
    """True when real Prometheus metrics are being collected."""
    return _AVAILABLE


def render() -> tuple[bytes, str]:
    """Return the Prometheus exposition payload and its content type.

    Raises ``RuntimeError`` when the extra is not installed — callers should
    guard with :func:`is_available`.
    """
    if not _AVAILABLE:
        raise RuntimeError("prometheus-client is not installed (pip install -e '.[obs]').")
    return generate_latest(), CONTENT_TYPE_LATEST