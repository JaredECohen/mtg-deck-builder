from __future__ import annotations

import pytest

from app.optimizer import OptimizerConstraints, validate_constraints
from app.optimizer.format_config import FORMATS, get_format_config
from app.optimizer.fitness import _archetype_mulligan_profile
from app.oracle.profile import (
    CardProfile,
    ComboPrimitives,
    CostVector,
    EffectVector,
    PROFILE_VERSION,
    RoleWeights,
)


def make_profile(name, *, cmc=1.0, role=None):
    return CardProfile(
        card_id=name,
        name=name,
        cost_vector=CostVector(cmc=cmc),
        effect_vector=EffectVector(),
        role_weights=RoleWeights(**(role or {})),
        combo_primitives=ComboPrimitives(),
        oracle_ast=[],
        profile_version=PROFILE_VERSION,
        parse_method="pattern",
    )


def test_format_config_modern_has_60_card_size():
    cfg = get_format_config("modern")
    assert cfg.deck_size == 60
    assert cfg.singleton is False
    assert cfg.starting_life == 20


def test_format_config_commander_singleton_99_cards():
    cfg = get_format_config("commander")
    assert cfg.deck_size == 99
    assert cfg.singleton is True
    assert cfg.has_commander is True
    assert cfg.starting_life == 40
    assert cfg.min_lands == 35


def test_format_config_unknown_raises():
    with pytest.raises(ValueError):
        get_format_config("vintage")


def test_constraints_inherit_from_format():
    """OptimizerConstraints should pull deck_size/min_lands from format."""
    c = OptimizerConstraints(format="commander")
    assert c.deck_size == 99
    assert c.min_lands == 35
    assert c.singleton is True


def test_constraints_user_overrides_take_precedence():
    c = OptimizerConstraints(format="modern", deck_size=42, max_lands=20)
    assert c.deck_size == 42
    assert c.max_lands == 20


def test_validate_singleton_format_caps_at_one():
    """Commander format: 2 copies of a non-basic is illegal."""
    bolt = make_profile("Lightning Bolt", role={"removal": 1.0})
    forest = make_profile("Forest", role={"land": 1.0})
    deck = [(bolt, "Instant"), (bolt, "Instant")] + [(forest, "Basic Land — Forest")] * 97
    constraints = OptimizerConstraints(format="commander", commander_name="Anhelo")
    violations = validate_constraints(deck, constraints)
    codes = {v.code for v in violations}
    assert "over_playset" in codes


def test_validate_singleton_basics_uncapped():
    """Forests can repeat any number of times even in Commander."""
    forest = make_profile("Forest", role={"land": 1.0})
    deck = [(forest, "Basic Land — Forest")] * 99
    constraints = OptimizerConstraints(format="commander", commander_name="Yeva")
    violations = validate_constraints(deck, constraints)
    assert all(v.code != "over_playset" for v in violations)


def test_validate_commander_requires_commander_name():
    forest = make_profile("Forest", role={"land": 1.0})
    deck = [(forest, "Basic Land — Forest")] * 99
    no_commander = OptimizerConstraints(format="commander")
    violations = validate_constraints(deck, no_commander)
    codes = {v.code for v in violations}
    assert "missing_commander" in codes


def test_validate_modern_4of_cap_unchanged():
    """Modern still caps non-basics at 4, 5 copies should fail."""
    bolt = make_profile("Lightning Bolt", role={"removal": 1.0})
    forest = make_profile("Mountain", role={"land": 1.0})
    deck = [(bolt, "Instant")] * 5 + [(forest, "Basic Land — Mountain")] * 55
    c = OptimizerConstraints(format="modern")
    violations = validate_constraints(deck, c)
    codes = {v.code for v in violations}
    assert "over_playset" in codes


def test_format_size_violation_for_each_format():
    forest = make_profile("Forest", role={"land": 1.0})
    for fmt_name, cfg in FORMATS.items():
        deck = [(forest, "Basic Land — Forest")] * 30  # too small
        c = OptimizerConstraints(
            format=fmt_name,
            commander_name="Test Commander" if cfg.has_commander else None,
        )
        violations = validate_constraints(deck, c)
        codes = {v.code for v in violations}
        assert "size" in codes, f"format {fmt_name} should flag size violation"


def test_mulligan_profile_inherits_format_floor():
    """Commander aggro should still demand ≥3 lands (format floor)
    instead of the aggro default of (2, 4)."""
    profile = _archetype_mulligan_profile("aggro", format_id="commander")
    assert profile.ideal_lands[0] >= 3  # format floor wins
    assert profile.ideal_lands[1] >= 5


def test_mulligan_profile_modern_aggro_unchanged():
    profile = _archetype_mulligan_profile("aggro", format_id="modern")
    assert profile.ideal_lands == (2, 5)  # Modern floor lo=2, hi=5; aggro asks (2,4) but format hi=5 wins


def test_legacy_minimum_lands_lower_than_modern():
    legacy = get_format_config("legacy")
    modern = get_format_config("modern")
    assert legacy.min_lands < modern.min_lands  # Legacy mana is more efficient
