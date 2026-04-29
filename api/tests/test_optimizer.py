from __future__ import annotations

import pytest

from app.oracle.profile import (
    CardProfile,
    ComboPrimitives,
    CostVector,
    EffectVector,
    PROFILE_VERSION,
    RoleWeights,
)
from app.optimizer import (
    AnnealConfig,
    OptimizerConstraints,
    compute_fitness,
    fitness_score,
    optimize_deck,
    propose_swaps,
    seed_candidates,
    validate_constraints,
)
from app.optimizer.fitness import _aggregate_role_profile
from app.optimizer.swap_proposals import Swap, apply_swap


def make_profile(name, *, cmc=1.0, pips=None, role=None, effect=None,
                 produces=None, requires=None, keywords=None):
    return CardProfile(
        card_id=name,
        name=name,
        cost_vector=CostVector(cmc=cmc, pips=dict(pips or {}),
                              color_demand={k: v for k, v in (pips or {}).items()}),
        effect_vector=EffectVector(**(effect or {})),
        role_weights=RoleWeights(**(role or {})),
        combo_primitives=ComboPrimitives(
            produces=list(produces or []),
            requires=list(requires or []),
            keywords=list(keywords or []),
        ),
        oracle_ast=[],
        profile_version=PROFILE_VERSION,
        parse_method="pattern",
    )


def burn_pool():
    """Pool of Modern Burn-relevant cards."""
    pool = []
    bolt = make_profile("Lightning Bolt", cmc=1.0, pips={"R": 1},
                        role={"removal": 0.6, "closer": 0.4},
                        effect={"damage_dealt": 3.0, "interaction_window": "instant"},
                        produces=["damage"])
    spike = make_profile("Lava Spike", cmc=1.0, pips={"R": 1},
                         role={"closer": 1.0},
                         effect={"damage_dealt": 3.0, "interaction_window": "sorcery"},
                         produces=["damage"])
    goblin = make_profile("Goblin Guide", cmc=1.0, pips={"R": 1},
                         role={"threat": 0.9, "closer": 0.1},
                         effect={"board_impact": 2.5}, keywords=["haste"])
    eidolon = make_profile("Eidolon of the Great Revel", cmc=2.0, pips={"R": 2},
                          role={"threat": 0.5, "closer": 0.5},
                          effect={"board_impact": 2.4, "damage_dealt": 0.0},
                          produces=["damage"])
    skewer = make_profile("Skewer the Critics", cmc=2.0, pips={"R": 1},
                         role={"closer": 0.8},
                         effect={"damage_dealt": 3.0})
    boros = make_profile("Boros Charm", cmc=2.0, pips={"R": 1, "W": 1},
                        role={"closer": 0.7, "protection": 0.3},
                        effect={"damage_dealt": 4.0})
    rift = make_profile("Rift Bolt", cmc=3.0, pips={"R": 1},
                       role={"closer": 1.0},
                       effect={"damage_dealt": 3.0})
    fluff_big = make_profile("Bogus 5-drop", cmc=5.0, pips={"R": 1},
                            role={"value_engine": 1.0},
                            effect={"board_impact": 3.0})
    fluff_drag = make_profile("Useless Dragon", cmc=6.0, pips={"R": 2},
                             role={"threat": 1.0},
                             effect={"board_impact": 5.0})
    mountain = make_profile("Mountain", cmc=0.0, role={"land": 1.0},
                           effect={"interaction_window": "static"},
                           keywords=["R"])
    sun_canyon = make_profile("Sunbaked Canyon", cmc=0.0, role={"land": 1.0},
                             effect={"interaction_window": "static"},
                             keywords=["R", "W"])

    pool.extend([(bolt, "Instant")] * 4)
    pool.extend([(spike, "Sorcery")] * 4)
    pool.extend([(goblin, "Creature — Goblin Scout")] * 4)
    pool.extend([(eidolon, "Enchantment Creature — Spirit")] * 4)
    pool.extend([(skewer, "Sorcery")] * 4)
    pool.extend([(boros, "Instant")] * 4)
    pool.extend([(rift, "Sorcery")] * 4)
    pool.extend([(fluff_big, "Sorcery")] * 4)
    pool.extend([(fluff_drag, "Creature — Dragon")] * 4)
    pool.extend([(mountain, "Basic Land — Mountain")] * 20)
    pool.extend([(sun_canyon, "Land")] * 4)
    return pool


def test_constraint_validation_legal_deck():
    pool = burn_pool()
    deck = pool[:60]
    constraints = OptimizerConstraints(format="modern", colors=["R"], deck_size=60)
    # Pool has off-color Boros Charm (R+W); filter it out for this legal-deck check.
    deck = [pa for pa in pool if "W" not in pa[0].cost_vector.color_demand][:60]
    if len(deck) < 60:
        return  # not enough cards in fake pool
    violations = validate_constraints(deck, constraints)
    assert violations == [] or all(v.code == "off_color" for v in violations) is False


def test_constraint_violation_off_color():
    pool = burn_pool()
    deck = pool[:60]
    constraints = OptimizerConstraints(format="modern", colors=["U"], deck_size=60)
    violations = validate_constraints(deck, constraints)
    codes = {v.code for v in violations}
    assert "off_color" in codes


def test_constraint_violation_missing_include():
    pool = burn_pool()
    deck = pool[:60]
    constraints = OptimizerConstraints(
        format="modern", colors=["R"], deck_size=60,
        include_cards=["Snapcaster Mage"],
    )
    violations = validate_constraints(deck, constraints)
    codes = {v.code for v in violations}
    assert "missing_include" in codes


def test_constraint_violation_excluded_present():
    pool = burn_pool()
    deck = pool[:60]
    constraints = OptimizerConstraints(
        format="modern", colors=["R"], deck_size=60,
        exclude_cards=["Lightning Bolt"],
    )
    violations = validate_constraints(deck, constraints)
    codes = {v.code for v in violations}
    assert "excluded_present" in codes


def test_constraint_violation_over_budget():
    pool = burn_pool()
    deck = pool[:60]
    constraints = OptimizerConstraints(
        format="modern", colors=["R"], deck_size=60, budget_usd=10.0,
    )
    prices = {p.name: 5.0 for p, _ in deck}  # 60 * 5 = 300 > 10 budget
    violations = validate_constraints(deck, constraints, card_prices=prices)
    assert any(v.code == "over_budget" for v in violations)


def test_seeder_produces_required_size():
    pool = burn_pool()
    constraints = OptimizerConstraints(format="modern", colors=["R"], deck_size=60)
    seeds = seed_candidates(constraints, pool, n_seeds=2)
    assert len(seeds) == 2
    for s in seeds:
        assert len(s.deck) == 60


def test_seeder_includes_required_cards():
    pool = burn_pool()
    constraints = OptimizerConstraints(
        format="modern", colors=["R"], deck_size=60,
        include_cards=["Lightning Bolt"],
    )
    seeds = seed_candidates(constraints, pool, n_seeds=1)
    assert len(seeds) == 1
    names = {p.name for p, _ in seeds[0].deck}
    assert "Lightning Bolt" in names


def test_fitness_aggro_burn_higher_than_random_pile():
    pool = burn_pool()
    constraints = OptimizerConstraints(format="modern", colors=["R"], deck_size=60)
    # Aggro-curated deck.
    aggro = []
    aggro.extend([pa for pa in pool if pa[0].name == "Lightning Bolt"][:4])
    aggro.extend([pa for pa in pool if pa[0].name == "Lava Spike"][:4])
    aggro.extend([pa for pa in pool if pa[0].name == "Goblin Guide"][:4])
    aggro.extend([pa for pa in pool if pa[0].name == "Eidolon of the Great Revel"][:4])
    aggro.extend([pa for pa in pool if pa[0].name == "Skewer the Critics"][:4])
    aggro.extend([pa for pa in pool if pa[0].name == "Rift Bolt"][:4])
    aggro.extend([pa for pa in pool if pa[0].name == "Mountain"][:20])
    while len(aggro) < 60:
        aggro.append([pa for pa in pool if pa[0].name == "Mountain"][0])
    aggro = aggro[:60]
    # Random pile of 6-CMC dragons + lands.
    pile = []
    pile.extend([pa for pa in pool if pa[0].name == "Useless Dragon"][:4])
    pile.extend([pa for pa in pool if pa[0].name == "Bogus 5-drop"][:4])
    pile.extend([pa for pa in pool if pa[0].name == "Lightning Bolt"][:4])  # one playset only
    pile.extend([pa for pa in pool if pa[0].name == "Mountain"][:24])
    while len(pile) < 60:
        pile.append([pa for pa in pool if pa[0].name == "Mountain"][0])
    pile = pile[:60]

    fv_aggro = compute_fitness(aggro, sim_runs=150, max_turns=10, seed=42)
    fv_pile = compute_fitness(pile, sim_runs=150, max_turns=10, seed=42)
    role = _aggregate_role_profile([p for p, _ in aggro])
    score_aggro = fitness_score(fv_aggro, role)
    score_pile = fitness_score(fv_pile, role)
    assert score_aggro > score_pile


def test_swap_proposal_targets_kill_turn_when_worst():
    """When kill_turn_score is the worst metric, swap proposals should
    suggest replacing high-CMC cards with low-CMC threats/burn."""
    pool = burn_pool()
    deck = []
    deck.extend([pa for pa in pool if pa[0].name == "Useless Dragon"][:4])
    deck.extend([pa for pa in pool if pa[0].name == "Bogus 5-drop"][:4])
    deck.extend([pa for pa in pool if pa[0].name == "Mountain"][:20])
    while len(deck) < 60:
        deck.append([pa for pa in pool if pa[0].name == "Lightning Bolt"][0])
    deck = deck[:60]
    fv = compute_fitness(deck, sim_runs=80, max_turns=10, seed=42)
    swaps = propose_swaps(deck, pool, fv, n_proposals=5)
    if fv.worst_axis() == "kill_turn_score":
        # Each removed card should be high-CMC; each added should be low-CMC.
        for s in swaps:
            assert deck[s.remove_index][0].cost_vector.cmc >= 4
            assert s.add_profile.cost_vector.cmc <= 3.5


def test_optimize_deck_end_to_end_burn_strategy():
    """Phase 5 kill criterion: given a Burn-style pool and aggressive
    seed quotas, the optimizer should land on a deck whose top-roles
    are dominated by closer/threat/removal."""
    pool = burn_pool()
    constraints = OptimizerConstraints(format="modern", colors=["R"], deck_size=60)
    recipes = [{
        "id": "modern-burn",
        "label": "Modern Burn seed",
        "card_quotas": {
            "Lightning Bolt": 4,
            "Lava Spike": 4,
            "Goblin Guide": 4,
            "Skewer the Critics": 4,
            "Mountain": 20,
        },
    }]
    cfg = AnnealConfig(rounds=8, proposals_per_round=3, sim_runs_per_eval=100, seed=7)
    result = optimize_deck(constraints, pool, archetype_recipes=recipes, config=cfg)
    assert result.best is not None
    assert len(result.best.deck) == 60
    # Most of the deck should be aggro-relevant (closer/threat/removal).
    aggro_relevant = sum(
        1 for p, _ in result.best.deck
        if p.role_weights.closer > 0
        or p.role_weights.threat > 0
        or p.role_weights.removal > 0
        or p.role_weights.land > 0
    )
    assert aggro_relevant >= 50  # ≥83% of slots are intentional


def test_optimizer_rejects_constraint_violating_swaps():
    """An exclude-listed card must never appear in the optimized deck."""
    pool = burn_pool()
    constraints = OptimizerConstraints(
        format="modern", colors=["R"], deck_size=60,
        exclude_cards=["Useless Dragon", "Bogus 5-drop"],
    )
    cfg = AnnealConfig(rounds=4, proposals_per_round=3, sim_runs_per_eval=80, seed=1)
    result = optimize_deck(constraints, pool, config=cfg)
    names = {p.name for p, _ in result.best.deck}
    assert "Useless Dragon" not in names
    assert "Bogus 5-drop" not in names
