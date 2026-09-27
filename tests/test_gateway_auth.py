"""Tier 1 auth: JWT/OAuth dispatch, static token, dev/prod safety, rate-limit key."""

import sys
import types

import pytest
from fastapi import HTTPException

from arthaai.gateway import auth


class _Settings:
    def __init__(
        self,
        dev_mode=True,
        oauth_jwks_url="",
        oauth_audience="",
        oauth_issuer="",
        oauth_algorithms="RS256",
    ):
        self.dev_mode = dev_mode
        self.oauth_jwks_url = oauth_jwks_url
        self.oauth_audience = oauth_audience
        self.oauth_issuer = oauth_issuer
        self.oauth_algorithms = oauth_algorithms


class _Request:
    def __init__(self, headers=None, cookies=None, host="1.2.3.4"):
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.client = type("C", (), {"host": host})()


# ---- token extraction / rate-limit key --------------------------------------

def test_extract_token_prefers_bearer_header():
    assert auth._extract_token("Bearer abc", "cookie-val") == "abc"


def test_extract_token_falls_back_to_cookie():
    assert auth._extract_token(None, "cookie-val") == "cookie-val"


def test_extract_token_none():
    assert auth._extract_token(None, None) is None
    assert auth._extract_token("Basic abc", None) is None


def test_client_key_hashes_token_and_is_stable():
    a = auth.client_key(_Request(headers={"authorization": "Bearer secret"}))
    b = auth.client_key(_Request(headers={"authorization": "Bearer secret"}))
    c = auth.client_key(_Request(headers={"authorization": "Bearer other"}))
    assert a == b and a != c
    assert "secret" not in a  # raw token never used as the key


def test_client_key_falls_back_to_ip():
    assert auth.client_key(_Request(host="9.9.9.9")) == "9.9.9.9"


# ---- require_principal dispatch ---------------------------------------------

def test_missing_token_is_401():
    with pytest.raises(HTTPException) as exc:
        auth.require_principal(authorization=None, arthaai_token=None)
    assert exc.value.status_code == 401


def test_static_token_accepted(monkeypatch):
    monkeypatch.setattr("arthaai.gateway.auth.get_settings", lambda: _Settings(dev_mode=False))
    monkeypatch.setattr("arthaai.security.vault.get_secret", lambda *a, **kw: "sekret")
    p = auth.require_principal(authorization="Bearer sekret", arthaai_token=None)
    assert p.subject == "investor"


def test_static_token_wrong_is_403(monkeypatch):
    monkeypatch.setattr("arthaai.gateway.auth.get_settings", lambda: _Settings(dev_mode=False))
    monkeypatch.setattr("arthaai.security.vault.get_secret", lambda *a, **kw: "sekret")
    with pytest.raises(HTTPException) as exc:
        auth.require_principal(authorization="Bearer wrong", arthaai_token=None)
    assert exc.value.status_code == 403


def test_dev_mode_without_config_accepts_any_bearer(monkeypatch):
    monkeypatch.setattr("arthaai.gateway.auth.get_settings", lambda: _Settings(dev_mode=True))
    monkeypatch.setattr("arthaai.security.vault.get_secret", lambda *a, **kw: None)
    p = auth.require_principal(authorization="Bearer whatever", arthaai_token=None)
    assert p.subject == "dev"


def test_production_without_config_refuses(monkeypatch):
    monkeypatch.setattr("arthaai.gateway.auth.get_settings", lambda: _Settings(dev_mode=False))
    monkeypatch.setattr("arthaai.security.vault.get_secret", lambda *a, **kw: None)
    with pytest.raises(HTTPException) as exc:
        auth.require_principal(authorization="Bearer whatever", arthaai_token=None)
    assert exc.value.status_code == 503


# ---- JWT path ----------------------------------------------------------------

def test_jwt_mode_without_pyjwt_is_503(monkeypatch):
    monkeypatch.setitem(sys.modules, "jwt", None)  # force ImportError
    monkeypatch.setattr(
        "arthaai.gateway.auth.get_settings",
        lambda: _Settings(dev_mode=False, oauth_jwks_url="https://idp/jwks"),
    )
    with pytest.raises(HTTPException) as exc:
        auth.require_principal(authorization="Bearer tok", arthaai_token=None)
    assert exc.value.status_code == 503


def _install_fake_jwt(monkeypatch, decode):
    fake = types.ModuleType("jwt")

    class _SigningKey:
        key = "resolved-signing-key"

    class _JWKClient:
        def __init__(self, url):
            self.url = url

        def get_signing_key_from_jwt(self, token):
            return _SigningKey()

    fake.PyJWKClient = _JWKClient
    fake.decode = decode
    monkeypatch.setitem(sys.modules, "jwt", fake)


def test_jwt_claims_become_principal(monkeypatch):
    captured = {}

    def decode(token, key, algorithms=None, audience=None, issuer=None, options=None):
        captured.update(token=token, key=key, algorithms=algorithms, audience=audience,
                        issuer=issuer, options=options)
        return {"sub": "alice", "scope": "analyze:read trade:write", "exp": 9999999999}

    _install_fake_jwt(monkeypatch, decode)
    s = _Settings(
        dev_mode=False, oauth_jwks_url="https://idp/jwks",
        oauth_audience="arthaai", oauth_issuer="https://idp",
    )
    p = auth._verify_jwt("tok", s)
    assert p.subject == "alice"
    assert p.scopes == ("analyze:read", "trade:write")
    assert captured["key"] == "resolved-signing-key"
    assert captured["algorithms"] == ["RS256"]
    assert captured["options"] == {"require": ["exp"]}  # expiry is mandatory


def test_jwt_decode_failure_is_401(monkeypatch):
    def decode(*a, **kw):
        raise ValueError("signature verification failed")

    _install_fake_jwt(monkeypatch, decode)
    s = _Settings(dev_mode=False, oauth_jwks_url="https://idp/jwks")
    with pytest.raises(HTTPException) as exc:
        auth._verify_jwt("tok", s)
    assert exc.value.status_code == 401
