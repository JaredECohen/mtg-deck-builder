from __future__ import annotations

import pytest

from app.oracle import parse_mana_cost, parse_oracle_text, build_card_profile
from app.oracle.profile import PROFILE_VERSION


def test_parse_simple_mana_cost():
    v = parse_mana_cost("{2}{R}{R}")
    assert v.generic == 2
    assert v.pips["R"] == 2
    assert v.cmc == 4
    assert v.color_demand["R"] == 2


def test_parse_hybrid_mana_cost():
    v = parse_mana_cost("{R/G}")
    assert v.color_demand["R"] == pytest.approx(0.5)
    assert v.color_demand["G"] == pytest.approx(0.5)
    assert v.cmc == 1


def test_parse_phyrexian_mana_cost():
    v = parse_mana_cost("{B/P}")
    assert any("phyrexian" in alt for alt in v.alt_costs)
    assert v.cmc == 1


def test_parse_x_cost():
    v = parse_mana_cost("{X}{R}")
    assert v.pips["X"] == 1
    assert v.pips["R"] == 1
    assert "x_cost" in v.alt_costs


def test_parse_2brid_cost():
    v = parse_mana_cost("{2/W}")
    assert v.generic == 2
    assert v.cmc == 2


def test_lightning_bolt():
    effects, coverage, residual = parse_oracle_text(
        "Lightning Bolt deals 3 damage to any target.", name="Lightning Bolt"
    )
    assert coverage >= 0.99
    assert not residual
    assert len(effects) == 1
    eff = effects[0]
    assert eff.trigger == "none"
    assert any(a.kind == "damage" and a.quantity == 3 for a in eff.actions)


def test_counterspell():
    effects, coverage, _ = parse_oracle_text("Counter target spell.", name="Counterspell")
    assert coverage == 1.0
    assert any(a.kind == "counter" for a in effects[0].actions)


def test_brainstorm():
    effects, coverage, _ = parse_oracle_text(
        "Draw three cards, then put two cards from your hand on top of your library in any order.",
        name="Brainstorm",
    )
    assert coverage >= 0.99
    draws = [a for eff in effects for a in eff.actions if a.kind == "draw"]
    assert sum(a.quantity for a in draws) >= 3


def test_etb_trigger():
    text = "When ~ enters the battlefield, draw a card."
    effects, _, _ = parse_oracle_text(text, name=None)
    assert effects[0].trigger == "etb"
    assert any(a.kind == "draw" for a in effects[0].actions)


def test_activated_ability():
    effects, _, _ = parse_oracle_text("{T}: Add {G}.", name=None)
    assert effects[0].trigger == "activated"
    assert effects[0].cost == "{T}"
    assert any(a.kind == "add_mana" for a in effects[0].actions)


def test_storm_payoff_keyword_only():
    effects, coverage, residual = parse_oracle_text(
        "Storm",
        name=None,
    )
    assert coverage == 1.0


def test_residual_clauses_reported():
    text = "This spell costs {1} less to cast for each artifact you control."
    effects, coverage, residual = parse_oracle_text(text, name=None)
    assert coverage < 1.0
    assert residual


def test_lightning_bolt_full_profile():
    card = {
        "name": "Lightning Bolt",
        "mana_cost": "{R}",
        "mana_value": 1,
        "type_line": "Instant",
        "oracle_text": "Lightning Bolt deals 3 damage to any target.",
        "keywords": [],
        "tags": ["interaction", "burn"],
        "color_identity": ["R"],
    }
    profile = build_card_profile(card)
    assert profile.profile_version == PROFILE_VERSION
    assert profile.cost_vector.cmc == 1
    assert profile.cost_vector.pips["R"] == 1
    assert profile.effect_vector.damage_dealt == 3
    assert profile.effect_vector.interaction_window == "instant"
    assert profile.role_weights.removal > 0
    assert profile.parse_method == "pattern"


def test_counterspell_full_profile():
    card = {
        "name": "Counterspell",
        "mana_cost": "{U}{U}",
        "mana_value": 2,
        "type_line": "Instant",
        "oracle_text": "Counter target spell.",
        "keywords": [],
        "tags": ["interaction", "counter"],
        "color_identity": ["U"],
    }
    profile = build_card_profile(card)
    assert profile.effect_vector.is_counterspell is True
    assert profile.effect_vector.interaction_window == "instant"
    assert profile.role_weights.disruption > 0
    assert profile.role_weights.removal > 0


def test_creature_threat_profile():
    card = {
        "name": "Tarmogoyf",
        "mana_cost": "{1}{G}",
        "mana_value": 2,
        "type_line": "Creature — Lhurgoyf",
        "oracle_text": "Tarmogoyf's power is equal to the number of card types among cards in all graveyards and its toughness is equal to that number plus 1.",
        "keywords": [],
        "tags": ["threat"],
        "color_identity": ["G"],
        "power": "*",
        "toughness": "*",
    }
    profile = build_card_profile(card)
    assert profile.effect_vector.interaction_window == "permanent"
    assert profile.role_weights.land == 0


def test_land_profile():
    card = {
        "name": "Mountain",
        "mana_cost": "",
        "mana_value": 0,
        "type_line": "Basic Land — Mountain",
        "oracle_text": "({T}: Add {R}.)",
        "keywords": [],
        "tags": ["land", "mana"],
        "color_identity": ["R"],
    }
    profile = build_card_profile(card)
    assert profile.role_weights.land == 1.0
    assert profile.effect_vector.interaction_window == "static"


def test_treasure_token_producer():
    card = {
        "name": "Big Score",
        "mana_cost": "{3}{R}",
        "mana_value": 4,
        "type_line": "Sorcery",
        "oracle_text": "As an additional cost to cast this spell, discard a card. Draw two cards and create two Treasure tokens.",
        "keywords": [],
        "tags": ["draw"],
        "color_identity": ["R"],
    }
    profile = build_card_profile(card)
    assert profile.effect_vector.cards_drawn >= 2
    assert "mana_treasure" in profile.combo_primitives.produces


def test_role_weights_normalize():
    card = {
        "name": "Wrath of God",
        "mana_cost": "{2}{W}{W}",
        "mana_value": 4,
        "type_line": "Sorcery",
        "oracle_text": "Destroy all creatures. They can't be regenerated.",
        "keywords": [],
        "tags": ["interaction", "wrath"],
        "color_identity": ["W"],
    }
    profile = build_card_profile(card)
    total = sum(profile.role_weights.to_dict().values())
    assert 0.99 <= total <= 1.01 or total == 0


def test_evoke_alt_cost_extracted():
    card = {
        "name": "Grief",
        "mana_cost": "{1}{B}",
        "mana_value": 2,
        "type_line": "Creature — Elemental Incarnation",
        "oracle_text": "Menace. When Grief enters, target opponent reveals their hand. You choose a nonland card from it. That player discards that card. Evoke—Exile a black card from your hand.",
        "keywords": ["Menace", "Evoke"],
        "tags": ["disruption"],
        "color_identity": ["B"],
        "power": "3",
        "toughness": "2",
    }
    p = build_card_profile(card)
    assert any("evoke" in c for c in p.cost_vector.alt_costs)
    # Evoke clause should NOT be misclassified as exile-removal.
    assert not any("hand" in s.lower() for s in p.effect_vector.removal_scope)


def test_suspend_alt_cost_extracted():
    card = {
        "name": "Living End",
        "mana_cost": "{3}{B}{B}",
        "mana_value": 5,
        "type_line": "Sorcery",
        "oracle_text": "Suspend 3—{2}{B}. Each player exiles all creature cards from their graveyard, then sacrifices all creatures they control, then puts all cards they exiled this way onto the battlefield.",
        "keywords": ["Suspend"],
        "tags": ["combo"],
        "color_identity": ["B"],
    }
    p = build_card_profile(card)
    assert any("suspend" in c for c in p.cost_vector.alt_costs)


def test_dash_alt_cost_extracted():
    card = {
        "name": "Ragavan, Nimble Pilferer",
        "mana_cost": "{R}",
        "mana_value": 1,
        "type_line": "Legendary Creature — Monkey Pirate",
        "oracle_text": "Whenever Ragavan, Nimble Pilferer deals combat damage to a player, create a Treasure token and exile the top card of that player's library. Until end of turn, you may cast that card. Dash {1}{R}.",
        "keywords": ["Dash"],
        "tags": ["aggro"],
        "color_identity": ["R"],
        "power": "2",
        "toughness": "1",
    }
    p = build_card_profile(card)
    assert any("dash" in c for c in p.cost_vector.alt_costs)
    # "exile the top card" should not contaminate removal_scope.
    assert not any("top card" in s.lower() for s in p.effect_vector.removal_scope)


def test_force_of_negation_no_phantom_removal():
    card = {
        "name": "Force of Negation",
        "mana_cost": "{1}{U}{U}",
        "mana_value": 3,
        "type_line": "Instant",
        "oracle_text": "If it's not your turn, you may exile a blue card from your hand rather than pay this spell's mana cost. Counter target noncreature spell. If that spell is countered this way, exile it instead of putting it into its owner's graveyard.",
        "keywords": [],
        "tags": ["interaction", "counter"],
        "color_identity": ["U"],
    }
    p = build_card_profile(card)
    # The "exile a blue card from your hand" alt-cost text must NOT appear
    # as a removal target. Only "stack" (from the counter) should remain.
    assert "stack" in p.effect_vector.removal_scope
    assert not any("hand" in s.lower() for s in p.effect_vector.removal_scope)
    assert p.effect_vector.is_counterspell


def test_pump_instant_gets_enabler():
    card = {
        "name": "Monstrous Rage",
        "mana_cost": "{R}",
        "mana_value": 1,
        "type_line": "Instant",
        "oracle_text": "Target creature gets +2/+0 and gains trample until end of turn.",
        "keywords": [],
        "tags": ["aggro"],
        "color_identity": ["R"],
    }
    p = build_card_profile(card)
    assert p.role_weights.enabler > 0


def test_haste_keyword_extracted():
    card = {
        "name": "Slickshot Show-Off",
        "mana_cost": "{1}{R}",
        "mana_value": 2,
        "type_line": "Creature — Bird Wizard",
        "oracle_text": "Flying, haste, plot.",
        "keywords": ["Flying", "Haste"],
        "tags": ["aggro"],
        "color_identity": ["R"],
        "power": "1",
        "toughness": "1",
    }
    profile = build_card_profile(card)
    assert "haste" in profile.combo_primitives.keywords
    assert "flying" in profile.combo_primitives.keywords
