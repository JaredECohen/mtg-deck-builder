"""Sign-in rate-limit buckets are a keyed HMAC, not sha256(ip)."""

from __future__ import annotations

import hashlib
import hmac

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.auth_service import AuthService, connection_digest


def _engine():
    return create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _buckets(engine) -> list[str]:
    with engine.connect() as conn:
        return [row[0] for row in conn.execute(text("SELECT bucket FROM auth_rate_buckets"))]


def test_digest_is_keyed_hmac_not_sha256(monkeypatch):
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.setenv("RATE_LIMIT_HMAC_KEY", "key-one")
    coarse = "203.0.113.10"
    first = connection_digest(coarse)
    plain = hashlib.sha256(coarse.encode()).hexdigest()
    assert first == hmac.new(b"key-one", coarse.encode(), hashlib.sha256).hexdigest()
    assert first != plain
    monkeypatch.setenv("RATE_LIMIT_HMAC_KEY", "key-two")
    second = connection_digest(coarse)
    assert second != first
    assert second != plain
    assert second == hmac.new(b"key-two", coarse.encode(), hashlib.sha256).hexdigest()


def test_consume_ip_stores_the_hmac_and_not_the_address(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_HMAC_KEY", "key-one")
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    engine = _engine()
    accounts = AuthService(session_factory=sessionmaker(bind=engine, future=True))
    assert accounts.consume_ip("203.0.113.10") is True
    digest = hmac.new(b"key-one", b"203.0.113.10", hashlib.sha256).hexdigest()
    plain = hashlib.sha256(b"203.0.113.10").hexdigest()
    buckets = _buckets(engine)
    assert f"ip:{digest}" in buckets
    assert f"ip-day:{digest}" in buckets
    blob = " ".join(buckets)
    assert plain not in blob
    assert "203.0.113.10" not in blob


def test_email_network_bucket_depends_on_the_key(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_HMAC_KEY", "net-key")
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    engine = _engine()
    accounts = AuthService(session_factory=sessionmaker(bind=engine, future=True))
    assert accounts.consume_email_send("a@example.com", "203.0.113.8") is True
    material = b"a@example.com\n203.0.113.8"
    digest = hmac.new(b"net-key", material, hashlib.sha256).hexdigest()
    plain = hashlib.sha256(material).hexdigest()
    buckets = _buckets(engine)
    assert "email-net:" + digest in buckets
    blob = " ".join(buckets)
    assert plain not in blob
    assert "203.0.113.8" not in blob


def test_missing_key_fails_closed_in_production(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.delenv("RATE_LIMIT_HMAC_KEY", raising=False)
    assert connection_digest("203.0.113.50") is None
    engine = _engine()
    accounts = AuthService(session_factory=sessionmaker(bind=engine, future=True))
    assert accounts.consume_ip("203.0.113.50") is False
    assert accounts.consume_email_send("a@example.com", "203.0.113.50") is False
    assert _buckets(engine) == []
    plain = hashlib.sha256(b"203.0.113.50").hexdigest()
    assert plain not in " ".join(_buckets(engine))


def test_missing_key_outside_production_is_not_plain_sha256(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_HMAC_KEY", raising=False)
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    digest = connection_digest("198.51.100.8")
    assert digest
    assert digest != hashlib.sha256(b"198.51.100.8").hexdigest()
    assert connection_digest("198.51.100.8") == digest
