"""Spec-gap engine behaviour (docs/IMPLEMENTATION-PLAN-2026-10-12.md, stream A)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app, repository
from app.models import CardRecord
from app.rules import is_land_card

client = TestClient(app)


def _generate(**body) -> dict:
    response = client.post("/v1/decks/generate", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _names(deck: dict, section: str = "mainboard") -> set[str]:
    return {ref["name"] for ref in deck[section]}


def _count(refs: list[dict]) -> int:
    return sum(ref["quantity"] for ref in refs)


# ── A13: name lookup ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("typed", "canonical"),
    [
        ("Lim-Dul's Vault", "Lim-Dûl's Vault"),
        ("Æther Vial", "Aether Vial"),
        ("Fable of the Mirror-Breaker", "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki"),
        ("Reflection of Kiki-Jiki", "Fable of the Mirror-Breaker // Reflection of Kiki-Jiki"),
    ],
)
def test_spelling_variants_and_face_names_resolve(typed, canonical):
    card = repository.get_card(typed)
    assert card is not None and card.name == canonical


def test_ascii_spelling_validates():
    response = client.post("/v1/decks/validate", json={
        "format": "legacy",
        "mainboard": [{"name": "Lim-Dul's Vault", "quantity": 1}, {"name": "Swamp", "quantity": 59}],
    })
    assert not any("Unknown card" in error for error in response.json()["errors"])


# ── A14: MDFC land counting ──────────────────────────────────────────────


def test_spell_land_mdfc_counts_as_a_spell():
    spell_land = CardRecord(name="X // Y", type_line="Instant // Land")
    land_land = CardRecord(name="A // B", type_line="Land // Land")
    assert not is_land_card(spell_land)
    assert is_land_card(land_land)


# ── A2: includes, excludes, budget ───────────────────────────────────────


def test_commander_honors_includes_and_reports_dropped_ones():
    deck = _generate(
        format="commander",
        commander_name="Atraxa, Praetors' Voice",
        include_cards=["Doubling Season", "Lightning Bolt", "Totally Fake Card", "Black Lotus"],
    )
    assert "Doubling Season" in _names(deck)
    dropped = {item["name"]: item["reason"] for item in deck["provenance"]["dropped_includes"]}
    assert dropped == {"Lightning Bolt": "off_color", "Totally Fake Card": "unknown", "Black Lotus": "not_legal"}
    assert any("Lightning Bolt" in warning for warning in deck["warnings"])


def test_excluded_card_never_lands_in_the_sideboard():
    base = _generate(format="modern", colors=["R"], playstyle_tags=["aggro"])
    victim = base["sideboard"][0]["name"]
    deck = _generate(format="modern", colors=["R"], playstyle_tags=["aggro"], exclude_cards=[victim])
    assert victim not in _names(deck, "sideboard") | _names(deck)


def test_budget_build_swaps_or_drops_expensive_anchors_and_respects_the_cap():
    deck = _generate(format="modern", prompt="modern murktide", budget=80)
    assert deck["estimated_price_usd"] is not None and deck["estimated_price_usd"] <= 80
    for swap in deck["provenance"]["budget_substitutions"]:
        assert swap["replacement"] in _names(deck) | _names(deck, "sideboard")


def test_anchor_lands_do_not_bypass_the_budget():
    deck = _generate(format="modern", prompt="modern burn", budget=40)
    for ref in deck["mainboard"]:
        card = repository.get_card(ref["name"])
        if card is not None and is_land_card(card) and card.price_usd is not None:
            assert card.price_usd <= 40 * 0.12, ref


# ── A3: sideboards ───────────────────────────────────────────────────────


@pytest.mark.parametrize("fmt", ["standard", "pioneer", "modern", "legacy"])
def test_best_of_three_decks_get_a_full_sideboard(fmt):
    deck = _generate(format=fmt, colors=["W", "U"], playstyle_tags=["control"])
    assert _count(deck["sideboard"]) == 15
    assert deck["is_legal"], deck["validation_errors"]


def test_best_of_one_has_no_sideboard():
    deck = _generate(format="modern", colors=["R"], playstyle_tags=["aggro"], match_type="bo1")
    assert deck["sideboard"] == []
    assert deck["constraints"]["match_type"] == "bo1"


# ── A7: Commander brackets ───────────────────────────────────────────────


def test_bracket_assessment_reads_game_changers_combos_and_mld():
    from app.services.brackets import assess

    casual = assess(["Sol Ring", "Llanowar Elves", "Forest"], repository)
    assert casual.estimated == 2 and not casual.game_changers
    upgraded = assess(["Rhystic Study", "Smothering Tithe", "Forest"], repository)
    assert upgraded.estimated == 3 and upgraded.game_changers == ["Rhystic Study", "Smothering Tithe"]
    optimized = assess(["Armageddon", "Thassa's Oracle", "Demonic Consultation"], repository)
    assert optimized.estimated == 4
    assert optimized.mass_land_denial == ["Armageddon"]
    assert ["Thassa's Oracle", "Demonic Consultation"] in optimized.two_card_combos
    assert optimized.game_changers_as_of


@pytest.mark.parametrize("bracket", [1, 2])
def test_low_bracket_build_has_no_game_changers_or_combos(bracket):
    deck = _generate(format="commander", colors=["U", "B"], playstyle_tags=["control"], bracket=bracket)
    assert deck["bracket"] is not None
    assert deck["bracket"]["target"] == bracket
    assert deck["bracket"]["game_changers"] == []
    assert deck["bracket"]["mass_land_denial"] == []
    assert deck["bracket"]["two_card_combos"] == []


def test_bracket_three_allows_requested_game_changers_only():
    deck = _generate(
        format="commander", colors=["U", "B"], playstyle_tags=["control"], bracket=3,
        include_cards=["Rhystic Study"],
    )
    assert set(deck["bracket"]["game_changers"]) <= {"Rhystic Study"}
    assert "Rhystic Study" in _names(deck)


# ── A6: game plan ────────────────────────────────────────────────────────


@pytest.mark.parametrize("fmt", ["standard", "modern", "commander"])
def test_every_deck_gets_a_game_plan(fmt):
    body = {"format": fmt, "colors": ["R", "G"], "playstyle_tags": ["aggro"]}
    deck = _generate(**body)
    plan = deck["game_plan"]
    assert plan["summary"] and plan["win_conditions"] and plan["opening_hand"] and plan["mulligan"]
    in_deck = _names(deck) | ({deck["commander"]} if deck["commander"] else set())
    assert set(plan["win_conditions"]) <= in_deck
    if fmt != "commander":
        guided = {entry["card"] for entry in plan["sideboard_guide"]}
        assert guided == _names(deck, "sideboard")
        assert all(entry["take_out"] for entry in plan["sideboard_guide"])
    else:
        assert plan["commander_packages"]
