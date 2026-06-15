"""Tests for production wiring: API-key auth + the evaluate endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _sample_deck():
    # Built from cards present in the bundled sample dataset.
    return {
        "format": "modern",
        "mainboard": [
            {"name": "Lightning Bolt", "quantity": 16},
            {"name": "Lava Dart", "quantity": 4},
            {"name": "Forest", "quantity": 20},
            {"name": "Island", "quantity": 20},
        ],
        "games": 60,
        "seed": 3,
    }


def test_evaluate_endpoint_returns_bounded_metrics():
    resp = client.post("/v1/decks/evaluate", json=_sample_deck())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in (
        "flood_resistance", "screw_resistance", "interaction_resilience",
        "inevitability", "consistency", "win_rate",
    ):
        assert 0.0 <= body[key] <= 1.0
    assert body["cards_evaluated"] == 60
    lo, hi = body["win_rate_ci"]
    assert lo <= body["win_rate"] <= hi


def test_evaluate_reports_unresolved_cards():
    payload = _sample_deck()
    payload["mainboard"].append({"name": "Definitely Not A Real Card", "quantity": 1})
    resp = client.post("/v1/decks/evaluate", json=payload)
    assert resp.status_code == 200, resp.text
    assert "Definitely Not A Real Card" in resp.json()["unresolved_cards"]


def test_auth_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MTG_API_KEY", raising=False)
    resp = client.post("/v1/decks/evaluate", json=_sample_deck())
    assert resp.status_code == 200


def test_auth_enforced_when_key_set(monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "secret-key-123")
    # Missing header → 401.
    resp = client.post("/v1/decks/evaluate", json=_sample_deck())
    assert resp.status_code == 401
    # Wrong key → 401.
    resp = client.post("/v1/decks/evaluate", json=_sample_deck(),
                       headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401
    # Correct key → 200.
    resp = client.post("/v1/decks/evaluate", json=_sample_deck(),
                       headers={"X-API-Key": "secret-key-123"})
    assert resp.status_code == 200


def test_auth_supports_multiple_rotated_keys(monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "old-key, new-key")
    for key in ("old-key", "new-key"):
        resp = client.post("/v1/decks/evaluate", json=_sample_deck(),
                           headers={"X-API-Key": key})
        assert resp.status_code == 200
