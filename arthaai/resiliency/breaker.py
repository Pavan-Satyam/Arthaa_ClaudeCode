"""Circuit-breaker wrapper around external integration points (pybreaker).

Implements the blueprint's CLOSED / OPEN / HALF-OPEN state machine: after
`fail_max` consecutive failures the circuit OPENS and calls fail fast; after
`reset_timeout` it goes HALF-OPEN to probe recovery. When the circuit is open
(or the call errors) the provided `fallback` is invoked so the system degrades
gracefully instead of crashing.
"""

from __future__ import annotations

from typing import Callable, TypeVar

import pybreaker
import structlog

log = structlog.get_logger()
T = TypeVar("T")

# One breaker per named dependency so a failing vendor can't trip unrelated calls.
_breakers: dict[str, pybreaker.CircuitBreaker] = {}


def _get(name: str) -> pybreaker.CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = pybreaker.CircuitBreaker(fail_max=3, reset_timeout=30, name=name)
    return _breakers[name]


def breaker_state(name: str) -> str:
    return _get(name).current_state  # 'closed' | 'open' | 'half-open'


def guarded(name: str, fn: Callable[[], T], fallback: Callable[[], T]) -> T:
    """Call `fn` through the `name` circuit breaker; on trip/error use `fallback`."""
    breaker = _get(name)
    try:
        return breaker.call(fn)
    except pybreaker.CircuitBreakerError:
        log.warning("circuit_open", dependency=name, action="fallback")
        return fallback()
    except Exception as exc:  # noqa: BLE001 - degrade rather than propagate
        log.warning("dependency_error", dependency=name, error=str(exc), action="fallback")
        return fallback()
