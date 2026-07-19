"""Microservice resiliency — circuit breakers + graceful fallback (blueprint §8)."""

from arthaai.resiliency.breaker import guarded, breaker_state

__all__ = ["guarded", "breaker_state"]
