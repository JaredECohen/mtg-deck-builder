"""Wiring tests for compose-from-scratch + refine_compose. We don't have
LLM credits in CI so we monkeypatch the Anthropic client to inject canned
responses, then assert the generator threads through the refinement pass
correctly.

What these tests prove without burning a single Sonnet 4.6 call:
  1. compose_from_scratch is invoked when no builtin keyword matches.
  2. refine_compose IS invoked after compose, NOT instead of it.
  3. The refined card list (not the raw compose list) flows into the
     final DeckResponse via BuiltinArchetype.anchor_cards.
  4. When refine_compose returns None (LLM unavailable), the raw compose
     list is still used — graceful degradation.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from app.models import GenerateDeckRequest
from app.services import llm_service
from app.services.card_repository import CardRepository
from app.services.deck_generator import DeckGenerator
from app.services.deck_validator import DeckValidator


def _mock_anthropic_response(payload: dict) -> MagicMock:
    """Fake the Anthropic SDK's Message response object."""
    block = MagicMock()
    block.type = "text"
    block.text = json.dumps(payload)
    response = MagicMock()
    response.content = [block]
    return response


@pytest.fixture
def generator():
    r = CardRepository()
    v = DeckValidator(r)
    return DeckGenerator(r, v), r


@pytest.fixture(autouse=True)
def _reset_caches():
    """Each test gets fresh LLM caches so prior compose results don't leak."""
    llm_service._compose_cache.clear()
    llm_service._enrichment_cache.clear()
    yield


def test_compose_runs_when_no_builtin_matches(generator, monkeypatch):
    """When the brief contains no archetype keyword, compose_from_scratch
    must fire. We assert the mocked client got called exactly once for the
    compose pass (and a second time for refine_compose)."""
    deck_gen, repo = generator

    # Pick real cards that exist in the local card repository so the
    # downstream `if not repository.get_card(name): continue` filter
    # doesn't drop the entire compose result.
    compose_payload = {
        "archetype_label": "Mock Composed Shell",
        "strategy": "A draft strategy that the refiner will polish.",
        "anchor_cards": [
            {"name": "Lightning Bolt", "quantity": 4},
            {"name": "Goblin Guide", "quantity": 4},
            {"name": "Monastery Swiftspear", "quantity": 4},
        ],
    }
    refine_payload = {
        "archetype_label": "Mock Refined Shell",
        "strategy": "A tightened version with a bridge card added.",
        "anchor_cards": [
            {"name": "Lightning Bolt", "quantity": 4},
            {"name": "Goblin Guide", "quantity": 4},
            {"name": "Monastery Swiftspear", "quantity": 4},
            {"name": "Lava Spike", "quantity": 4},  # the "bridge card"
        ],
    }

    call_log: list[str] = []

    class FakeMessages:
        def create(self, *, system, messages, **kwargs):
            # Identify which prompt we're answering by looking at the
            # system block text. compose has "compose a complete anchor
            # card list from scratch"; refine has "tighten it."
            system_text = " ".join(
                block["text"] if isinstance(block, dict) else getattr(block, "text", "")
                for block in system
            )
            if "tighten it" in system_text:
                call_log.append("refine")
                return _mock_anthropic_response(refine_payload)
            if "compose" in system_text.lower() or "anchor card list from scratch" in system_text.lower():
                call_log.append("compose")
                return _mock_anthropic_response(compose_payload)
            # Anything else: identify the system prompt to help debug.
            call_log.append(f"other:{system_text[:60]!r}")
            return _mock_anthropic_response({"reply": "noop", "anchor_cards": []})

    fake_client = MagicMock()
    fake_client.messages = FakeMessages()
    monkeypatch.setattr(llm_service, "_get_client", lambda: fake_client)
    # interpret_generate_prompt also uses the client; stub it to return
    # an empty intent so the test is deterministic.
    monkeypatch.setattr(
        llm_service,
        "interpret_generate_prompt",
        lambda prompt: llm_service.GeneratePromptIntent(),
    )

    request = GenerateDeckRequest(
        format="modern",
        colors=["R"],
        # A brief with NO archetype keyword. "kaleidoscope motif" matches
        # nothing in BUILTIN_ARCHETYPES.
        prompt="build a modern deck with a kaleidoscope motif and a long-haul value engine",
        mode="constraint-aware",
        experience_level="beginner",
    )
    deck = deck_gen.generate(request)

    # Both passes ran in order. There may be incidental other LLM calls
    # (e.g. enrich_deck_analysis when deep_analysis is on) — we just
    # care that compose and refine both fired.
    assert "compose" in call_log, call_log
    assert "refine" in call_log, call_log
    assert call_log.index("compose") < call_log.index("refine"), call_log
    # The REFINED label/strategy made it into the response.
    assert deck.title.endswith("Mock Refined Shell"), deck.title
    assert "tightened" in deck.strategy_summary.lower(), deck.strategy_summary
    # Lava Spike (the bridge card injected by the refine pass) appears
    # in the final mainboard. If only the raw compose result had been
    # used, Lava Spike wouldn't be there.
    mainboard_names = {ref.name for ref in deck.mainboard}
    assert "Lava Spike" in mainboard_names, sorted(mainboard_names)


def test_refine_failure_falls_back_to_raw_compose(generator, monkeypatch):
    """If refine_compose raises, the generator must still produce a deck
    using the raw compose output. Graceful degradation."""
    deck_gen, repo = generator

    compose_payload = {
        "archetype_label": "Raw Composed",
        "strategy": "Strategy that survives even when refine fails.",
        "anchor_cards": [
            {"name": "Lightning Bolt", "quantity": 4},
            {"name": "Goblin Guide", "quantity": 4},
        ],
    }

    call_log: list[str] = []

    class FakeMessages:
        def create(self, *, system, messages, **kwargs):
            system_text = " ".join(
                block["text"] if isinstance(block, dict) else getattr(block, "text", "")
                for block in system
            )
            if "tighten it" in system_text:
                call_log.append("refine")
                # Simulate Anthropic API failure (depleted credits, network, etc.)
                raise RuntimeError("simulated LLM failure")
            if "compose" in system_text.lower() or "anchor card list from scratch" in system_text.lower():
                call_log.append("compose")
                return _mock_anthropic_response(compose_payload)
            call_log.append("other")
            return _mock_anthropic_response({"reply": "noop", "anchor_cards": []})

    fake_client = MagicMock()
    fake_client.messages = FakeMessages()
    monkeypatch.setattr(llm_service, "_get_client", lambda: fake_client)
    monkeypatch.setattr(
        llm_service,
        "interpret_generate_prompt",
        lambda prompt: llm_service.GeneratePromptIntent(),
    )

    request = GenerateDeckRequest(
        format="modern",
        colors=["R"],
        prompt="build a modern deck with an esoteric mosaic theme",
        mode="constraint-aware",
        experience_level="beginner",
    )
    deck = deck_gen.generate(request)

    # Both passes were attempted (incidental "other" LLM calls are fine).
    assert "compose" in call_log
    assert "refine" in call_log
    assert call_log.index("compose") < call_log.index("refine")
    # The RAW compose label survived (not the would-be refined one).
    assert "Raw Composed" in deck.title, deck.title
    # Mainboard contains the raw compose anchors.
    mainboard_names = {ref.name for ref in deck.mainboard}
    assert "Lightning Bolt" in mainboard_names
    assert "Goblin Guide" in mainboard_names
