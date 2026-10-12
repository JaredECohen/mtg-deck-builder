"""Public-surface hardening: no config leaks, bounded inputs, bounded LLM waits."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import llm_service

client = TestClient(app)


def test_data_status_does_not_expose_database_url() -> None:
    response = client.get("/api/data-status")
    assert response.status_code == 200
    body = response.json()
    assert "database_url" not in body
    assert body["database_backend"] in {"sqlite", "postgresql"}
    assert "sqlite:///" not in response.text and "postgresql://" not in response.text


def test_oversized_prompt_is_rejected_before_any_work() -> None:
    response = client.post("/v1/decks/generate", json={"format": "modern", "prompt": "x" * 2_001})
    assert response.status_code == 422


def test_oversized_decklist_is_rejected() -> None:
    mainboard = [{"name": f"Card {i}", "quantity": 1} for i in range(251)]
    response = client.post("/v1/decks/validate", json={"format": "modern", "mainboard": mainboard})
    assert response.status_code == 422


def test_oversized_deck_text_is_rejected() -> None:
    response = client.post("/v1/decks/parse", json={"format": "modern", "deck_text": "1 Island\n" * 20_000})
    assert response.status_code == 422


def test_empty_card_name_is_rejected() -> None:
    response = client.post(
        "/v1/decks/validate",
        json={"format": "modern", "mainboard": [{"name": "", "quantity": 4}]},
    )
    assert response.status_code == 422


def test_card_search_limit_is_clamped() -> None:
    response = client.get("/v1/cards", params={"query": "a", "limit": 100_000})
    assert response.status_code == 200
    assert len(response.json()["cards"]) <= 50


def test_commander_search_limit_is_clamped() -> None:
    response = client.get("/v1/commanders", params={"limit": 100_000})
    assert response.status_code == 200
    assert len(response.json()["commanders"]) <= 100


def test_optimizer_parameters_are_bounded(monkeypatch) -> None:
    monkeypatch.delenv("MTG_API_KEY", raising=False)
    response = client.post("/v1/jobs/optimize", json={"format": "modern", "rounds": 10_000})
    assert response.status_code == 422


def test_llm_client_has_a_short_timeout(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setattr(llm_service, "_client", None)
    try:
        llm_client = llm_service._get_client()
        assert llm_client is not None
        assert llm_client.timeout == llm_service.LLM_TIMEOUT_SECONDS
        assert llm_client.max_retries == llm_service.LLM_MAX_RETRIES
        assert llm_client.timeout <= 60
    finally:
        monkeypatch.setattr(llm_service, "_client", None)
