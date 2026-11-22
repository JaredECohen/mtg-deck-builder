"""Coarse usage events: secret, allowlist, geo, retention, and no IP columns."""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

import app.services.usage_events as usage
from app.db import get_engine
from app.db_models import Base
from app.main import app
from app.rate_limiter import public_rate_limiter, usage_write_limiter

client = TestClient(app)

_COLUMNS = {"id", "created_at", "event", "path", "country", "region", "city"}
_FORBIDDEN = {
    "ip",
    "ip_address",
    "ip_hash",
    "hashed_ip",
    "forwarded_for",
    "x_forwarded_for",
    "latitude",
    "longitude",
    "lat",
    "lon",
    "postal_code",
    "postcode",
    "zip",
}


@pytest.fixture(autouse=True)
def _clean_usage_events():
    usage.ensure_schema()
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM usage_events"))
    yield
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM usage_events"))


@pytest.fixture
def usage_secret(monkeypatch):
    monkeypatch.setenv("USAGE_INGEST_SECRET", "test-usage-secret")
    usage_write_limiter.reset()
    return "test-usage-secret"


def _headers(secret: str = "test-usage-secret", **extra: str) -> dict[str, str]:
    headers = {"x-usage-ingest-secret": secret, "content-type": "application/json"}
    headers.update(extra)
    return headers


def _stored() -> tuple[list[str], list[dict]]:
    engine = get_engine()
    with engine.connect() as conn:
        columns = [row[1] for row in conn.execute(text("PRAGMA table_info(usage_events)"))]
        result = conn.execute(text("SELECT * FROM usage_events ORDER BY id"))
        keys = list(result.keys())
        rows = [dict(zip(keys, row)) for row in result]
    return columns, rows


def test_create_all_adds_only_the_coarse_columns():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        info = list(conn.execute(text("PRAGMA table_info(usage_events)")))
    columns = {row[1] for row in info}
    nullable = {row[1]: row[3] for row in info}
    assert columns == _COLUMNS
    assert _FORBIDDEN.isdisjoint(columns)
    assert nullable["country"] == 0
    assert nullable["region"] == 0
    assert nullable["city"] == 0
    assert nullable["event"] == 1
    assert nullable["path"] == 1


def test_geo_present_is_stored(usage_secret):
    response = client.post(
        "/v1/usage",
        json={"event": "page_view", "path": "/blog/x", "country": "us", "region": "CA", "city": "São Paulo"},
        headers=_headers(usage_secret),
    )
    assert response.status_code == 204, response.text
    _columns, rows = _stored()
    assert len(rows) == 1
    assert rows[0]["country"] == "US"
    assert rows[0]["region"] == "CA"
    assert rows[0]["city"] == "São Paulo"
    assert rows[0]["event"] == "page_view"
    assert rows[0]["path"] == "/blog/x"


def test_missing_geo_is_null(usage_secret):
    omitted = client.post(
        "/v1/usage",
        json={"event": "deck_refined", "path": "/"},
        headers=_headers(usage_secret),
    )
    explicit = client.post(
        "/v1/usage",
        json={"event": "deck_shared", "path": "/library", "country": None, "region": "", "city": "  "},
        headers=_headers(usage_secret),
    )
    assert omitted.status_code == 204, omitted.text
    assert explicit.status_code == 204, explicit.text
    _columns, rows = _stored()
    assert len(rows) == 2
    for row in rows:
        assert row["country"] is None
        assert row["region"] is None
        assert row["city"] is None


def test_stored_row_has_no_ip_hash_forwarded_for_or_coordinates(usage_secret):
    ip_hash = hashlib.sha256(b"203.0.113.9").hexdigest()
    payload = {
        "event": "page_view",
        "path": "/privacy",
        "country": "US",
        "region": "NY",
        "city": "New York",
        "ip": "203.0.113.9",
        "ip_address": "203.0.113.9",
        "hashed_ip": ip_hash,
        "ip_hash": ip_hash,
        "forwarded_for": "198.51.100.77",
        "x_forwarded_for": "198.51.100.77",
        "latitude": 40.7128,
        "longitude": -74.006,
        "lat": 40.7128,
        "lon": -74.006,
        "postcode": "10001",
        "postal_code": "10001",
    }
    response = client.post(
        "/v1/usage",
        json=payload,
        headers=_headers(usage_secret, **{"x-forwarded-for": "198.51.100.77", "fly-client-ip": "203.0.113.9"}),
    )
    assert response.status_code == 204, response.text
    assert response.text == ""
    columns, rows = _stored()
    assert set(columns) == _COLUMNS
    assert _FORBIDDEN.isdisjoint(columns)
    assert len(rows) == 1
    blob = json.dumps(rows[0])
    for banned in ("203.0.113.9", "198.51.100.77", ip_hash, "10001", "40.7128", "-74.006", "forwarded"):
        assert banned not in blob
    assert rows[0]["country"] == "US"
    assert rows[0]["city"] == "New York"


def test_ip_shaped_geo_values_are_dropped(usage_secret):
    digest = hashlib.sha256(b"203.0.113.9").hexdigest()
    cases = [
        {"country": "203.0.113.9", "region": "2001:db8::1", "city": "127.0.0.1"},
        {"country": "US", "region": "CA", "city": digest},
        {"country": "US", "region": "40.7128,-74.006", "city": "8.8.8.8"},
    ]
    for geo in cases:
        response = client.post(
            "/v1/usage",
            json={"event": "page_view", "path": "/ip", **geo},
            headers=_headers(usage_secret),
        )
        assert response.status_code == 204, response.text
    _columns, rows = _stored()
    assert len(rows) == 3
    blob = json.dumps(rows)
    for banned in ("203.0.113.9", "2001:db8::1", "127.0.0.1", digest, "40.7128", "8.8.8.8"):
        assert banned not in blob
    assert rows[0]["country"] is None and rows[0]["region"] is None and rows[0]["city"] is None
    assert rows[1]["country"] == "US" and rows[1]["region"] == "CA" and rows[1]["city"] is None
    assert rows[2]["city"] is None and rows[2]["region"] is None


def test_city_is_length_capped_and_query_is_not_stored(usage_secret):
    city = "Oakland" + ("x" * 200)
    response = client.post(
        "/v1/usage",
        json={"event": "guide_viewed", "path": "/d/sekret-token?token=abc#frag", "country": "US", "city": city},
        headers=_headers(usage_secret),
    )
    assert response.status_code == 204, response.text
    _columns, rows = _stored()
    assert rows[0]["path"] == "/d"
    assert "sekret" not in rows[0]["path"]
    assert "token" not in rows[0]["path"]
    assert rows[0]["city"] == city[:80]
    assert len(rows[0]["city"]) == 80


def test_missing_or_wrong_secret_writes_nothing(usage_secret, monkeypatch):
    body = {"event": "page_view", "path": "/"}
    calls = {"n": 0}
    real = hmac.compare_digest

    def spy(left, right):
        calls["n"] += 1
        return real(left, right)

    monkeypatch.setattr(usage.hmac, "compare_digest", spy)
    missing = client.post("/v1/usage", json=body, headers={"content-type": "application/json"})
    wrong = client.post("/v1/usage", json=body, headers=_headers("not-the-secret"))
    right = client.post("/v1/usage", json=body, headers=_headers(usage_secret))
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert right.status_code == 204, right.text
    assert calls["n"] >= 1

    monkeypatch.delenv("USAGE_INGEST_SECRET", raising=False)
    unset = client.post("/v1/usage", json=body, headers=_headers("test-usage-secret"))
    assert unset.status_code == 401
    _columns, rows = _stored()
    assert len(rows) == 1
    assert rows[0]["path"] == "/"


def test_non_allowlisted_event_is_rejected(usage_secret):
    for event in ("not_an_event", "prompt_saved", "page_viewed"):
        response = client.post(
            "/v1/usage",
            json={"event": event, "path": "/", "country": "US"},
            headers=_headers(usage_secret),
        )
        assert response.status_code == 400, event
    assert usage.USAGE_EVENTS == (
        "page_view",
        "deck_generated",
        "deck_refined",
        "deck_exported",
        "deck_shared",
        "deck_page_viewed",
        "tcgplayer_cart_clicked",
        "guide_viewed",
    )
    for event in usage.USAGE_EVENTS:
        response = client.post(
            "/v1/usage",
            json={"event": event, "path": "/library"},
            headers=_headers(usage_secret),
        )
        assert response.status_code == 204, event
    _columns, rows = _stored()
    assert {row["event"] for row in rows} == set(usage.USAGE_EVENTS)


def test_oversized_payload_is_rejected(usage_secret):
    raw = json.dumps({"event": "page_view", "path": "/", "pad": "x" * 3000}).encode()
    assert len(raw) > usage.BODY_MAX
    response = client.post("/v1/usage", content=raw, headers=_headers(usage_secret))
    assert response.status_code == 413
    _columns, rows = _stored()
    assert rows == []


def test_write_rate_limit_triggers_without_storing_an_ip(usage_secret, monkeypatch):
    monkeypatch.setattr(usage_write_limiter, "limit", 2)
    body = {"event": "page_view", "path": "/"}
    assert client.post("/v1/usage", json=body, headers=_headers(usage_secret)).status_code == 204
    assert client.post("/v1/usage", json=body, headers=_headers(usage_secret)).status_code == 204
    limited = client.post("/v1/usage", json=body, headers=_headers(usage_secret))
    assert limited.status_code == 429
    _columns, rows = _stored()
    assert len(rows) == 2
    assert list(usage_write_limiter._timestamps) == ["usage"]


def test_usage_writes_skip_the_ip_rate_limiter(usage_secret, monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "proxy-key")
    monkeypatch.setattr(public_rate_limiter, "limit", 1)
    headers = _headers(
        usage_secret,
        **{"x-api-key": "proxy-key", "x-forwarded-for": "203.0.113.50"},
    )
    body = {"event": "page_view", "path": "/"}
    assert client.post("/v1/usage", json=body, headers=headers).status_code == 204
    assert client.post("/v1/usage", json=body, headers=headers).status_code == 204
    blob = json.dumps(_stored()[1])
    assert "203.0.113.50" not in blob
    assert "203.0.113.50" not in str(list(usage_write_limiter._timestamps))


def test_retention_purges_rows_older_than_13_months():
    now = datetime(2026, 11, 22, 12, 0, tzinfo=timezone.utc)
    cutoff = usage.retention_cutoff(now)
    assert cutoff == "2025-10-22T12:00:00+00:00"
    usage.insert_event(event="page_view", path="/old", country=None, region=None, city=None, created_at="2025-10-22T11:59:59+00:00")
    usage.insert_event(event="page_view", path="/boundary", country="US", region=None, city=None, created_at=cutoff)
    usage.insert_event(event="page_view", path="/fresh", country=None, region=None, city=None, created_at="2026-11-22T12:00:00+00:00")
    removed = usage.purge_expired(now)
    assert removed == 1
    _columns, rows = _stored()
    assert {row["path"] for row in rows} == {"/boundary", "/fresh"}


def test_boot_purge_runs_without_a_write(monkeypatch):
    monkeypatch.setenv("MTG_USAGE_PURGE_SCHEDULE", "0")
    usage.insert_event(event="page_view", path="/ancient", country=None, region=None, city=None, created_at="2020-01-01T00:00:00+00:00")
    usage.insert_event(event="page_view", path="/today", country=None, region=None, city=None, created_at="2026-11-22T00:00:00+00:00")
    usage.start_retention_schedule()
    _columns, rows = _stored()
    assert {row["path"] for row in rows} == {"/today"}


def test_retention_loop_purges_on_a_timer_without_writes():
    calls: list[int] = []
    waits = iter([False, False, True])
    usage.run_retention_loop(3600, stop=lambda _interval: next(waits), purge=lambda: calls.append(1))
    assert calls == [1, 1]


def test_retention_thread_stops_on_shutdown(monkeypatch):
    monkeypatch.setenv("MTG_USAGE_PURGE_SCHEDULE", "1")
    calls: list[int] = []
    monkeypatch.setattr(usage, "purge_expired", lambda: calls.append(1))
    usage._scheduler_started = False
    usage._stop.clear()
    usage.start_retention_schedule(interval_seconds=30)
    try:
        thread = usage._retention_thread
        assert thread is not None and thread.is_alive()
        assert calls == [1]
        usage.stop_retention_schedule()
        assert thread.is_alive() is False
        assert calls == [1]
    finally:
        usage.stop_retention_schedule()
