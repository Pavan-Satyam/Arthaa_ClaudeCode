"""Lightweight alerting (ARTHA-9).

Emits alerts to the standard logger and a Prometheus counter. No external pager
is wired (that is deploy infrastructure), but this is the hook so circuit-breaker
trips and other operational anomalies are observable and countable. Safe to call
without the ``obs`` extra (the counter is a no-op).
"""

from __future__ import annotations

import logging

from arthaai.observability import metrics

_log = logging.getLogger("arthaai.alerts")


def alert(kind: str, message: str, **fields) -> None:
    """Record an operational alert: log line + ``arthaai_alerts_total{kind}``."""
    _log.warning("ALERT %s: %s %s", kind, message, fields or "")
    try:
        metrics.ALERTS.labels(kind).inc()
    except Exception:  # noqa: BLE001 - alerting must never break the caller
        pass