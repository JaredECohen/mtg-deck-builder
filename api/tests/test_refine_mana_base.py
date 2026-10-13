"""A refinement must never gut the mana base (2026-10-12).

A chat proposal "swap Swan Song and the Islands for Burst Lightning and
Mountains" came back with zero lands, marked legal. The refine seeded the
deck's spells, the newly retrieved shell added its own on top, and the trim
back to 60 always removed basic lands first.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app, repository
from app.services import deck_generator as generator_module
from app.services.llm_service import RefinementIntent

client = TestClient(app)


def _generated_deck() -> dict:
    resp = client.post(
        "/v1/decks/generate",
        json={"format": "modern", "colors": ["U", "R"], "playstyle_tags": ["aggro", "spells"]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _refine_with(monkeypatch, deck: dict, intent: RefinementIntent) -> dict:
    monkeypatch.setattr(generator_module, "interpret_refinement", lambda prompt: intent)
    resp = client.post("/v1/decks/refine", json={"deck": deck, "refinement_prompt": "scripted"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _lands(deck: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for ref in deck["mainboard"]:
        card = repository.get_card(ref["name"])
        if card and "Land" in card.type_line:
            out[ref["name"]] = out.get(ref["name"], 0) + ref["quantity"]
    return out


def test_noop_refine_keeps_the_land_count(monkeypatch):
    deck = _generated_deck()
    refined = _refine_with(monkeypatch, deck, RefinementIntent())
    assert sum(_lands(refined).values()) == sum(_lands(deck).values())
    assert sum(ref["quantity"] for ref in refined["mainboard"]) == 60


def test_excluding_a_basic_replaces_it_instead_of_shrinking_the_mana_base(monkeypatch):
    deck = _generated_deck()
    lands = _lands(deck)
    basics_in_deck = [name for name in ("Island", "Mountain") if lands.get(name)]
    assert basics_in_deck, lands
    removed = basics_in_deck[0]
    kept = "Mountain" if removed == "Island" else "Island"

    refined = _refine_with(monkeypatch, deck, RefinementIntent(
        exclude_cards=[removed],
        include_cards=[kept],
        include_quantities={kept: 4},
    ))
    refined_lands = _lands(refined)
    assert removed not in refined_lands, refined_lands
    assert sum(refined_lands.values()) == sum(lands.values()), (lands, refined_lands)
    assert refined["is_legal"], refined["validation_errors"]


def test_requested_cards_survive_the_trim(monkeypatch):
    deck = _generated_deck()
    candidate = next(
        card.name
        for card in repository.list_cards_for_format("modern")
        if "Land" not in card.type_line
        and set(card.color_identity or card.colors) <= {"U", "R"}
        and card.name not in {ref["name"] for ref in deck["mainboard"]}
    )
    refined = _refine_with(monkeypatch, deck, RefinementIntent(
        include_cards=[candidate], include_quantities={candidate: 2},
    ))
    assert any(ref["name"] == candidate for ref in refined["mainboard"]), candidate
    assert sum(_lands(refined).values()) == sum(_lands(deck).values())
