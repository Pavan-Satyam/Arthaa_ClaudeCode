"""OAuth 2.1 / JWT verification against a real IdP JWKS (ARTHA-107).

These tests exercise the full signature-verification path — not a fake decoder.
An ephemeral RSA keypair is generated, its public half is served as a JWKS from a
local HTTP server, a real token is minted with ``jwt.encode``, and ``_verify_jwt``
must validate it end-to-end. Expiry, audience and signature failures must be
rejected.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

jwt = pytest.importorskip("jwt")
crypto = pytest.importorskip("cryptography")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from arthaai.gateway import auth  # noqa: E402

_ISSUER = "https://idp.test"
_AUDIENCE = "arthaai"
_KID = "test-kid"


def _b64u(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@pytest.fixture(scope="module")
def idp():
    """A local IdP: RSA keypair + JWKS HTTP server + token minter."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = key.public_key().public_numbers()
    jwks = {
        "keys": [{
            "kty": "RSA", "use": "sig", "alg": "RS256", "kid": _KID,
            "n": _b64u(numbers.n), "e": _b64u(numbers.e),
        }]
    }
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )

    body = json.dumps(jwks).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # silence the test server
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]

    def mint(**overrides) -> str:
        now = int(time.time())
        claims = {
            "sub": "alice",
            "scope": "analyze:read trade:write",
            "iss": _ISSUER,
            "aud": _AUDIENCE,
            "iat": now,
            "exp": now + 3600,
        }
        claims.update(overrides)
        return jwt.encode(claims, private_pem, algorithm="RS256", headers={"kid": _KID})

    yield {"url": f"http://127.0.0.1:{port}/jwks.json", "mint": mint, "pem": private_pem}
    server.shutdown()


class _Settings:
    dev_mode = False
    oauth_jwks_url = ""
    oauth_issuer = _ISSUER
    oauth_audience = _AUDIENCE
    oauth_algorithms = "RS256"


def _settings(url: str) -> _Settings:
    s = _Settings()
    s.oauth_jwks_url = url
    return s


class TestJwtVerification:
    def test_valid_token_verified_against_jwks(self, idp):
        token = idp["mint"]()
        principal = auth._verify_jwt(token, _settings(idp["url"]))
        assert principal.subject == "alice"
        assert principal.scopes == ("analyze:read", "trade:write")

    def test_expired_token_is_401(self, idp):
        token = idp["mint"](exp=int(time.time()) - 10)
        with pytest.raises(HTTPException) as exc:
            auth._verify_jwt(token, _settings(idp["url"]))
        assert exc.value.status_code == 401

    def test_wrong_audience_is_401(self, idp):
        token = idp["mint"](aud="someone-else")
        with pytest.raises(HTTPException) as exc:
            auth._verify_jwt(token, _settings(idp["url"]))
        assert exc.value.status_code == 401

    def test_wrong_issuer_is_401(self, idp):
        token = idp["mint"](iss="https://evil.test")
        with pytest.raises(HTTPException) as exc:
            auth._verify_jwt(token, _settings(idp["url"]))
        assert exc.value.status_code == 401

    def test_tampered_signature_is_401(self, idp):
        other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        other_pem = other.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        now = int(time.time())
        token = jwt.encode(
            {"sub": "mallory", "iss": _ISSUER, "aud": _AUDIENCE, "exp": now + 3600},
            other_pem, algorithm="RS256", headers={"kid": _KID},
        )
        with pytest.raises(HTTPException) as exc:
            auth._verify_jwt(token, _settings(idp["url"]))
        assert exc.value.status_code == 401

    def test_require_principal_uses_jwt_path(self, idp, monkeypatch):
        monkeypatch.setattr(
            "arthaai.gateway.auth.get_settings", lambda: _settings(idp["url"])
        )
        principal = auth.require_principal(
            authorization=f"Bearer {idp['mint']()}", arthaai_token=None
        )
        assert principal.subject == "alice"