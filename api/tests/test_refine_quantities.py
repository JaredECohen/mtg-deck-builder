"""A refinement that states a count ("add 4x Lightning Bolt") must land that
many copies (2026-09-19). Before, `RefinementIntent` carried names only and
`DeckGenerator.refine` seeded every included card at one copy, so the chat's
"Cut 4x Mishra's Bauble, add 4x Expressive Iteration" produced 1x."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services import deck_generator as generator_module
from app.services.llm_service import RefinementIntent

client = TestClient(app)


def _generated_deck() -> dict:
    resp = client.post(
        "/v1/decks/generate",
        json={"format": "modern", "colors": ["U", "R"], "playstyle_tags": ["aggro", "spells"], "mode": "constraint-aware"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _count(deck: dict, name: str) -> int:
    return sum(ref["quantity"] for ref in deck["mainboard"] if ref["name"] == name)


def _refine_with(monkeypatch, deck: dict, intent: RefinementIntent) -> dict:
    monkeypatch.setattr(generator_module, "interpret_refinement", lambda prompt: intent)
    resp = client.post("/v1/decks/refine", json={"deck": deck, "refinement_prompt": "scripted"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_intent_parses_quantities_leniently():
    intent = RefinementIntent.model_validate({
        "include_cards": ["Lightning Bolt", "Consider"],
        "include_quantities": {"Lightning Bolt": "4", " Consider ": 2, "Junk": 0, "Bad": "x"},
    })
    assert intent.include_quantities == {"Lightning Bolt": 4, "Consider": 2}
    assert intent.requested_copies("lightning bolt") == 4
    assert intent.requested_copies("Opt") is None
    assert RefinementIntent.model_validate({"include_quantities": ["not", "a", "dict"]}).include_quantities == {}


# A card the sample pool has but the generated shell does not carry, so only the
# refinement can put it in the deck (Lightning Bolt is a core card of the shell
# and the archetype packages would re-add it regardless of the intent).
ADDED = "Lava Dart"


def _total(deck: dict) -> int:
    return sum(ref["quantity"] for ref in deck["mainboard"])


def _with_one_copy(deck: dict, name: str) -> dict:
    """Swap one basic for one copy of `name`, keeping the constructed 60-card minimum."""
    for ref in deck["mainboard"]:
        if ref["name"] == "Mountain" and ref["quantity"] > 1:
            ref["quantity"] -= 1
            break
    deck["mainboard"].append({"name": name, "quantity": 1})
    return deck


def test_stated_count_becomes_the_number_of_copies(monkeypatch):
    deck = _generated_deck()
    assert _count(deck, ADDED) == 0
    refined = _refine_with(monkeypatch, deck, RefinementIntent(
        include_cards=[ADDED], include_quantities={ADDED: 4},
    ))
    assert _count(refined, ADDED) == 4
    assert _total(refined) == 60


def test_stated_count_raises_an_existing_lower_count(monkeypatch):
    deck = _with_one_copy(_generated_deck(), ADDED)
    refined = _refine_with(monkeypatch, deck, RefinementIntent(
        include_cards=[ADDED], include_quantities={ADDED: 3},
    ))
    assert _count(refined, ADDED) == 3
    assert _total(refined) == 60


def test_a_card_named_without_a_count_still_seeds_one_copy(monkeypatch):
    deck = _generated_deck()
    refined = _refine_with(monkeypatch, deck, RefinementIntent(include_cards=[ADDED]))
    assert _count(refined, ADDED) == 1
    assert _total(refined) == 60


def test_a_lower_count_than_the_deck_runs_changes_nothing(monkeypatch):
    deck = _generated_deck()
    before = _count(deck, "Lightning Bolt")
    assert before == 4
    refined = _refine_with(monkeypatch, deck, RefinementIntent(
        include_cards=["Lightning Bolt"], include_quantities={"Lightning Bolt": 2},
    ))
    assert _count(refined, "Lightning Bolt") == before
