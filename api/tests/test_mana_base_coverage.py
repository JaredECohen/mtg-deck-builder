"""Generated mana bases must support every color the deck actually plays.

Regression for the WB lifegain bug where a mono-W corpus land package
(28 Plains) was grafted onto a WB request, leaving Fatal Push and
Thoughtseize uncastable.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

BASICS = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}


def test_two_color_deck_gets_sources_for_both_colors() -> None:
    response = client.post(
        "/v1/decks/generate",
        json={
            "format": "modern",
            "colors": ["W", "B"],
            "playstyle_tags": ["midrange"],
            "theme_tags": ["lifegain"],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["is_legal"] is True
    counts = {c["name"]: c["quantity"] for c in payload["mainboard"]}
    assert counts.get("Plains", 0) > 0, "white sources missing"
    assert counts.get("Swamp", 0) >= 4, f"black sources too thin: {counts}"
    # No skewed-package blowout: total lands within the validator's bounds.
    land_total = sum(q for n, q in counts.items() if n in BASICS)
    assert land_total <= 27


def test_mulligan_does_not_duplicate_cards() -> None:
    """The London mulligan loop must never grow the library."""
    import random

    from app.sim.mulligan import MulliganProfile, london_mulligan_loop
    from app.sim.state import CardInPlay, GameState
    from app.oracle.profile import (
        CardProfile,
        ComboPrimitives,
        CostVector,
        EffectVector,
        RoleWeights,
    )

    def make_card(name: str, is_land: bool) -> CardInPlay:
        profile = CardProfile(
            card_id=name,
            name=name,
            cost_vector=CostVector(cmc=1.0, pips={}, color_demand={}),
            effect_vector=EffectVector(),
            role_weights=RoleWeights(),
            combo_primitives=ComboPrimitives(),
        )
        return CardInPlay(profile=profile, is_land=is_land)

    library = [make_card(f"Spell {i}", is_land=False) for i in range(53)]
    library += [make_card("Mountain", is_land=True) for _ in range(7)]
    state = GameState(seed=7, library=library, hand=[])
    state.rng = random.Random(7)
    # Impossible keep threshold forces max mulligans.
    profile = MulliganProfile(keep_threshold=2.0)
    london_mulligan_loop(state, profile, max_mulligans=3)
    total = len(state.library) + len(state.hand)
    assert total == 60, f"cards duplicated or lost: {total}"
    names = [c.name for c in state.library + state.hand]
    assert len(names) == len(set(id(c) for c in state.library + state.hand))
