"""Observability — Prometheus metrics and OpenTelemetry tracing (ARTHA-507/508)."""

from fastapi.testclient import TestClient

from arthaai.gateway.app import app
from arthaai.observability import metrics, tracing


class TestMetrics:
    def test_available_with_extra(self):
        assert metrics.is_available() is True

    def test_render_returns_prometheus_payload(self):
        metrics.HTTP_REQUESTS.labels("GET", "/test", "200").inc()
        payload, content_type = metrics.render()
        assert isinstance(payload, bytes)
        assert b"arthaai_http_requests_total" in payload
        assert "text/plain" in content_type

    def test_gateway_metrics_endpoint_requires_auth(self):
        client = TestClient(app)
        assert client.get("/metrics").status_code == 401

    def test_gateway_metrics_endpoint_authenticated(self):
        client = TestClient(app)
        cookie = client.get("/").cookies.get("arthaai_token")
        resp = client.get("/metrics", cookies={"arthaai_token": cookie})
        assert resp.status_code == 200
        assert b"arthaai_http_requests_total" in resp.content


class TestTracing:
    def test_available_with_extra(self):
        assert tracing.is_available() is True

    def test_configure_is_idempotent(self):
        assert tracing.configure("arthaai-test") is True
        assert tracing.configure("arthaai-test") is True

    def test_span_sets_attributes(self):
        tracing.configure("arthaai-test")
        with tracing.span("unit-test", **{"arthaai.symbol": "GLD"}) as current:
            assert current is not None
            assert current.get_span_context().is_valid


class TestGatewayInstrumentation:
    def test_request_counted_by_middleware(self):
        client = TestClient(app)
        client.get("/")  # dashboard — no DB dependency
        cookie = client.get("/").cookies.get("arthaai_token")
        resp = client.get("/metrics", cookies={"arthaai_token": cookie})
        assert b"arthaai_http_requests_total" in resp.content


class TestAlerts:
    def test_alert_logs_and_counts(self):
        from arthaai.observability import alerts

        alerts.alert("unit_test", "something happened", dependency="x")
        payload, _ = metrics.render()
        assert b"arthaai_alerts_total" in payload

    def test_breaker_failure_raises_alert(self):
        from arthaai.resiliency.breaker import guarded

        def boom():
            raise RuntimeError("down")

        assert guarded("unit_dep", boom, lambda: "fallback") == "fallback"
        payload, _ = metrics.render()
        assert b"arthaai_alerts_total" in payload


class TestLlmCallTracking:
    def test_reason_counts_provider_calls(self):
        from arthaai.agents import master_llm

        master_llm.reason({"db": {"last_close": 100.0}}, "GLD")
        payload, _ = metrics.render()
        assert b"arthaai_llm_calls_total" in payload