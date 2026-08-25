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


def test_ohlcv_requires_auth():
    resp = client.get("/ohlcv/GLD")
    assert resp.status_code == 401


def test_ohlcv_rejects_non_bearer():
    resp = client.get("/ohlcv/GLD", headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401


def test_dashboard_sets_httponly_cookie():
    resp = client.get("/")
    assert resp.status_code == 200
    # The token must NOT be in the HTML body — it's in an httpOnly cookie.
    assert "__ARTHAAI_TOKEN__" not in resp.text
    assert "arthaai_token=" in resp.headers.get("set-cookie", "")
    assert "httponly" in resp.headers.get("set-cookie", "").lower()


def test_dashboard_cookie_authenticates_ohlcv(monkeypatch):
    """The cookie set by the dashboard must authenticate /ohlcv (same-origin).

    Mocks the DB layer so we test only the auth path — the cookie must get
    past require_principal (no 401/403).
    """
    import pandas as pd

    empty_df = pd.DataFrame(columns=["ts", "open", "high", "low", "close"])

    # Mock the DB so /ohlcv returns immediately without a real connection.
    monkeypatch.setattr("arthaai.db.timescale.load_ohlcv", lambda sym, limit=120: empty_df)
    monkeypatch.setattr("arthaai.data.ingest.ingest", lambda sym: None)

    # First request: get the cookie from the dashboard
    dash = client.get("/")
    cookie_val = dash.cookies.get("arthaai_token")
    assert cookie_val is not None
    # Second request: use the cookie to access /ohlcv
    resp = client.get("/ohlcv/GLD", cookies={"arthaai_token": cookie_val})
    assert resp.status_code not in (401, 403)
    assert resp.json()["symbol"] == "GLD"


def test_dashboard_refuses_dev_token_in_production(monkeypatch):
    """In non-dev mode, the dashboard must refuse to serve with a dev-token fallback."""
    # Force dev_mode=False and ensure no token is available
    monkeypatch.setattr("arthaai.config.get_settings", lambda: type("S", (), {
        "dev_mode": False, "risk_free_rate": 0.04, "kelly_fraction": 0.25,
        "max_single_instrument": 0.05, "vault_addr": "", "vault_token": "",
    })())
    monkeypatch.setattr(
        "arthaai.security.vault.get_secret",
        lambda path, key, env=None: None,  # no token available
    )
    # TestClient raises by default on server exceptions; we expect a 500.
    prod_client = TestClient(app, raise_server_exceptions=False)
    resp = prod_client.get("/")
    assert resp.status_code == 500  # RuntimeError -> 500
