"""`POST /v1/decks/chat` is gated by the optional API key like the other
LLM-spending endpoints (2026-09-19). Before that it sat behind the per-IP rate
limiter only, with no UI calling it."""

from __future__ import annotations

from functools import lru_cache

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@lru_cache(maxsize=1)
def _generated_deck() -> dict:
    # A real DeckResponse from the (ungated, offline) generator on the sample
    # dataset — hand-writing one drifts from the schema.
    resp = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["U", "R"],
            "playstyle_tags": ["aggro", "spells"],
            "theme_tags": ["prowess"],
            "mode": "constraint-aware",
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _chat_payload():
    return {"deck": _generated_deck(), "message": "What is the win condition?", "history": []}


def test_chat_requires_key_when_auth_enabled(monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "secret-key-123")
    resp = client.post("/v1/decks/chat", json=_chat_payload())
    assert resp.status_code == 401
    resp = client.post("/v1/decks/chat", json=_chat_payload(), headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


def test_chat_with_valid_key_reaches_the_handler(monkeypatch):
    # Auth passes; without an Anthropic key the handler reports the LLM as
    # unavailable (503) rather than rejecting the caller (401) — proving the
    # gate sits in front of, not instead of, the existing behaviour.
    monkeypatch.setenv("MTG_API_KEY", "secret-key-123")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post("/v1/decks/chat", json=_chat_payload(), headers={"X-API-Key": "secret-key-123"})
    assert resp.status_code in (503, 200), resp.text
    assert resp.status_code != 401


def test_chat_open_when_auth_disabled(monkeypatch):
    monkeypatch.delenv("MTG_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    resp = client.post("/v1/decks/chat", json=_chat_payload())
    assert resp.status_code in (503, 200), resp.text
