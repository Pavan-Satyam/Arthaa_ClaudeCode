"""mTLS termination awareness — fail-closed, trusted-proxy bound (ARTHA-110)."""

import pytest
from fastapi import HTTPException

from arthaai.gateway import mtls


class _Client:
    def __init__(self, host):
        self.host = host


class _Request:
    def __init__(self, headers=None, host="203.0.113.10"):
        self.headers = headers or {}
        self.client = _Client(host)


class _Settings:
    def __init__(self, mtls_required=True, dev_mode=False, proxies="203.0.113.0/24"):
        self.mtls_required = mtls_required
        self.dev_mode = dev_mode
        self.mtls_client_ca = ""
        self.mtls_trusted_proxies = proxies


class TestClientCertVerified:
    def test_trusted_proxy_with_envoy_xfcc(self):
        req = _Request({"x-forwarded-client-cert": "By=spiffe://..."})
        assert mtls.client_cert_verified(req, "203.0.113.0/24") is True

    def test_nginx_ssl_client_verify_success(self):
        req = _Request({"x-ssl-client-verify": "SUCCESS"})
        assert mtls.client_cert_verified(req, "203.0.113.0/24") is True

    def test_nginx_ssl_client_verify_failure(self):
        req = _Request({"x-ssl-client-verify": "FAILED"})
        assert mtls.client_cert_verified(req, "203.0.113.0/24") is False

    def test_untrusted_source_is_rejected(self):
        req = _Request({"x-forwarded-client-cert": "By=spiffe://..."}, host="198.51.100.7")
        assert mtls.client_cert_verified(req, "203.0.113.0/24") is False

    def test_no_trusted_proxies_configured_is_false(self):
        req = _Request({"x-forwarded-client-cert": "By=spiffe://..."})
        assert mtls.client_cert_verified(req, "") is False

    def test_no_headers_is_false(self):
        assert mtls.client_cert_verified(_Request(), "203.0.113.0/24") is False


class TestRequireMtls:
    def test_disabled_is_noop(self, monkeypatch):
        monkeypatch.setattr(mtls, "get_settings", lambda: _Settings(mtls_required=False))
        mtls.require_mtls(_Request())  # no raise

    def test_dev_mode_is_noop(self, monkeypatch):
        monkeypatch.setattr(
            mtls, "get_settings", lambda: _Settings(mtls_required=True, dev_mode=True)
        )
        mtls.require_mtls(_Request())  # no raise

    def test_required_without_trusted_proxy_is_403(self, monkeypatch):
        monkeypatch.setattr(
            mtls, "get_settings", lambda: _Settings(mtls_required=True, dev_mode=False, proxies="")
        )
        with pytest.raises(HTTPException) as exc:
            mtls.require_mtls(_Request({"x-forwarded-client-cert": "anything"}))
        assert exc.value.status_code == 403

    def test_required_without_cert_is_403(self, monkeypatch):
        monkeypatch.setattr(mtls, "get_settings", lambda: _Settings())
        with pytest.raises(HTTPException) as exc:
            mtls.require_mtls(_Request())
        assert exc.value.status_code == 403

    def test_required_with_trusted_verified_cert_passes(self, monkeypatch):
        monkeypatch.setattr(mtls, "get_settings", lambda: _Settings())
        mtls.require_mtls(_Request({"x-ssl-client-verify": "SUCCESS"}))  # no raise

    def test_spoofed_header_from_untrusted_source_is_403(self, monkeypatch):
        monkeypatch.setattr(mtls, "get_settings", lambda: _Settings())
        req = _Request({"x-forwarded-client-cert": "anything"}, host="198.51.100.7")
        with pytest.raises(HTTPException) as exc:
            mtls.require_mtls(req)
        assert exc.value.status_code == 403