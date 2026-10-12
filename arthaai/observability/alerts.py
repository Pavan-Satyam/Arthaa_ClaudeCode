"""Lightweight alerting (ARTHA-5).

Emits alerts to the standard logger, a Prometheus counter, and a bounded
in-process ring buffer so the dashboard can surface recent operational events.
No external pager is wired (that is deploy infrastructure), but this is the hook
so circuit-breaker trips and other anomalies are observable and countable. Safe
to call without the ``obs`` extra (the counter is a no-op).
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

from arthaai.observability import metrics

_log = logging.getLogger("arthaai.alerts")
_RECENT: deque[dict[str, Any]] = deque(maxlen=100)


def alert(kind: str, message: str, **fields) -> None:
    """Record an operational alert: log line, ``arthaai_alerts_total{kind}``, ring buffer."""
    _RECENT.append(
        {
            "ts": datetime.now(UTC).isoformat(),
            "kind": kind,
            "message": message,
            "fields": dict(fields),
        }
    )
    _log.warning("ALERT %s: %s %s", kind, message, fields or "")
    try:
        metrics.ALERTS.labels(kind).inc()
    except Exception as exc:  # noqa: BLE001 - alerting must never break the caller
        _log.debug("alert counter unavailable: %s", exc)


def recent(limit: int = 20) -> list[dict[str, Any]]:
    """Most recent alerts, newest first (read-only view for the dashboard)."""
    if limit < 1:
        return []
    return list(_RECENT)[-limit:][::-1]
