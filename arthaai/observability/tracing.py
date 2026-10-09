"""OpenTelemetry tracing for the ArthaAI pipeline (ARTHA-507).

Optional dependency: with no OTel SDK installed, :func:`span` yields ``None`` and
:func:`configure` is a no-op, so tracing is strictly opt-in. Install with the
``obs`` extra: ``pip install -e ".[obs]"``.

Tracing is only exported when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set (standard
OTel env var); otherwise spans are created locally and dropped, which keeps tests
and local runs free of a collector requirement.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

try:  # optional
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _AVAILABLE = True
except Exception:  # noqa: BLE001 - tracing must never break the app
    _AVAILABLE = False

_TRACER_NAME = "arthaai"
_configured = False


def is_available() -> bool:
    """True when the OpenTelemetry SDK is importable."""
    return _AVAILABLE


def configure(service_name: str = "arthaai") -> bool:
    """Install a TracerProvider; attach an OTLP exporter when configured.

    Returns True when a provider was installed. Idempotent.
    """
    global _configured
    if not _AVAILABLE or _configured:
        return _AVAILABLE
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        except Exception:  # noqa: BLE001 - exporter failure degrades to local spans
            pass
    trace.set_tracer_provider(provider)
    _configured = True
    return True


@contextmanager
def span(name: str, **attributes):
    """Context manager yielding the active span (or None when unavailable)."""
    if not _AVAILABLE:
        yield None
        return
    tracer = trace.get_tracer(_TRACER_NAME)
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            try:
                current.set_attribute(key, value)
            except Exception:  # noqa: BLE001
                pass
        yield current