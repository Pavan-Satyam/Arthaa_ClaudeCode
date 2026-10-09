"""Cross-cutting observability — Prometheus metrics and OpenTelemetry tracing.

Both are optional (the ``obs`` extra). Importing this package is always safe;
each submodule degrades to a no-op when its dependency is absent.
"""

from arthaai.observability import metrics, tracing

__all__ = ["metrics", "tracing"]