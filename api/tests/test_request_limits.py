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


# ── Gating, proxies, caching (A20-A22) ───────────────────────────────────

import app.main as main_module  # noqa: E402

_BODY = {"format": "modern", "colors": ["R"], "playstyle_tags": ["aggro"]}


def test_llm_spending_routes_need_the_key_when_auth_is_on(monkeypatch):
    monkeypatch.setenv("MTG_API_KEY", "k-123")
    assert client.post("/v1/decks/generate", json=_BODY).status_code == 401
    deck = client.post("/v1/decks/generate", json=_BODY, headers={"X-API-Key": "k-123"})
    assert deck.status_code == 200
    refine = {"deck": deck.json(), "refinement_prompt": "make it cheaper"}
    assert client.post("/v1/decks/refine", json=refine).status_code == 401
    analyze = {"format": "modern", "mainboard": [{"name": "Mountain", "quantity": 60}], "deep_analysis": False}
    assert client.post("/v1/decks/analyze", json=analyze).status_code == 401
    # Public reads stay open.
    assert client.post("/v1/decks/validate", json={"format": "modern", "mainboard": [{"name": "Mountain", "quantity": 60}]}).status_code == 200


def test_forwarded_for_is_trusted_only_when_configured(monkeypatch):
    class _Req:
        headers = {"x-forwarded-for": "203.0.113.7, 10.0.0.1"}

        class client:  # noqa: N801
            host = "10.0.0.1"

    monkeypatch.setattr(main_module, "TRUST_FORWARDED", False)
    assert main_module.client_key(_Req()) == "10.0.0.1"
    monkeypatch.setattr(main_module, "TRUST_FORWARDED", True)
    assert main_module.client_key(_Req()) == "203.0.113.7"


def test_forwarded_for_is_trusted_from_the_keyed_proxy(monkeypatch):
    """A public API behind the web proxy: only requests carrying the key (the
    proxy's) may name the client IP; direct callers can't spoof it."""
    monkeypatch.setattr(main_module, "TRUST_FORWARDED", False)
    monkeypatch.setenv("MTG_API_KEY", "proxy-key")

    class _Proxied:
        headers = {"x-forwarded-for": "203.0.113.7", "x-api-key": "proxy-key"}

        class client:  # noqa: N801
            host = "10.0.0.1"

    class _Spoofed:
        headers = {"x-forwarded-for": "203.0.113.7", "x-api-key": "wrong"}

        class client:  # noqa: N801
            host = "198.51.100.9"

    assert main_module.client_key(_Proxied()) == "203.0.113.7"
    assert main_module.client_key(_Spoofed()) == "198.51.100.9"


def test_identical_generate_requests_are_served_from_cache(monkeypatch):
    first = client.post("/v1/decks/generate", json=_BODY).json()
    calls = []
    monkeypatch.setattr(main_module.generator, "generate", lambda request: calls.append(request))
    second = client.post("/v1/decks/generate", json=_BODY).json()
    assert calls == []  # never reached the generator
    assert second["deck_id"] == first["deck_id"]


def test_public_routes_are_rate_limited(monkeypatch):
    from app import rate_limiter

    monkeypatch.setattr(rate_limiter.public_rate_limiter, "limit", 3)
    statuses = [client.get("/v1/meta/summary", params={"format": "modern"}).status_code for _ in range(5)]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[-1] == 429


def test_stale_card_data_is_noted(monkeypatch):
    monkeypatch.setattr(main_module.repository, "card_data_is_stale", lambda today=None: True)
    deck = client.post("/v1/decks/generate", json={**_BODY, "playstyle_tags": ["burn"]}).json()
    assert any("Card data is as of" in note for note in deck["provenance"]["notes"])
