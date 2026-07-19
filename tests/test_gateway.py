"""Tier 1 gateway — auth seam and routing (no datastore needed)."""

from fastapi.testclient import TestClient

from arthaai.gateway.app import app

client = TestClient(app)


def test_analyze_requires_bearer():
    resp = client.post("/analyze/GLD")
    assert resp.status_code == 401


def test_analyze_rejects_non_bearer():
    resp = client.post("/analyze/GLD", headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401


def test_health_is_open():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["service"] == "arthaai-gateway"
