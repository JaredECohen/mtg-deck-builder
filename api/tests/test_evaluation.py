"""Tests for the deck-evaluation layer (sim/evaluation.py)."""

from __future__ import annotations

import pytest

from app.sim import evaluate_deck, wilson_interval
from app.sim.evaluation import _card_advantage_density
from app.sim.meta_archetypes import burn, midrange_goodstuff_cmd, mono_red_std
from app.optimizer.fitness import compute_fitness, fitness_score, _aggregate_role_profile


def test_wilson_interval_basic_properties():
    lo, hi = wilson_interval(50, 100)
    assert 0.0 <= lo < 0.5 < hi <= 1.0
    # All wins → interval hugs 1.0 but never exceeds it.
    lo2, hi2 = wilson_interval(100, 100)
    assert hi2 <= 1.0 and lo2 > 0.5
    # No games → degenerate.
    assert wilson_interval(0, 0) == (0.0, 0.0)
    # More samples → tighter interval.
    w_small = wilson_interval(5, 10)
    w_big = wilson_interval(500, 1000)
    assert (w_big[1] - w_big[0]) < (w_small[1] - w_small[0])


def test_evaluate_deck_fields_are_bounded():
    ev = evaluate_deck(mono_red_std(), format_id="standard", games=120, seed=11)
    d = ev.to_dict()
    for key in (
        "flood_resistance", "screw_resistance", "interaction_resilience",
        "inevitability", "consistency", "card_advantage_density", "win_rate",
    ):
        assert 0.0 <= d[key] <= 1.0, f"{key}={d[key]} out of [0,1]"
    lo, hi = ev.win_rate_ci
    assert lo <= ev.win_rate <= hi


def test_evaluation_is_deterministic():
    a = evaluate_deck(mono_red_std(), format_id="standard", games=100, seed=5)
    b = evaluate_deck(mono_red_std(), format_id="standard", games=100, seed=5)
    assert a.to_dict() == b.to_dict()


def test_disruption_lowers_win_rate_for_burn():
    """Burn's clock is its spells; answering a quarter of them must hurt,
    so interaction_resilience should be well below 1.0."""
    ev = evaluate_deck(burn(), format_id="modern", games=200, seed=9,
                       disruption_rate=0.3)
    assert ev.interaction_resilience < 0.95


def test_commander_value_deck_has_card_advantage():
    density = _card_advantage_density(midrange_goodstuff_cmd())
    assert density > 0.0


def test_deep_eval_populates_resilience_and_inevitability():
    deck = mono_red_std()
    shallow = compute_fitness(deck, sim_runs=80, max_turns=10, seed=3,
                              format_id="standard")
    deep = compute_fitness(deck, sim_runs=80, max_turns=10, seed=3,
                           format_id="standard", deep_eval=True, deep_eval_games=80)
    # Shallow leaves the deep axes neutral; deep_eval fills them with real
    # simulator output and records the full evaluation in raw.
    assert shallow.resilience == 0.5 and shallow.inevitability == 0.5
    assert deep.raw.get("deep_eval")
    assert 0.0 <= deep.resilience <= 1.0
    assert 0.0 <= deep.inevitability <= 1.0


def test_worst_axis_never_returns_neutral_deep_axes():
    """resilience / inevitability / matchup are graded but not
    swap-targetable, so worst_axis must never pick them."""
    deck = mono_red_std()
    fv = compute_fitness(deck, sim_runs=60, max_turns=10, seed=1,
                         format_id="standard")
    assert fv.worst_axis() in {
        "kill_turn_score", "mulligan_keep", "mana_consistency",
        "synergy_density", "redundancy", "role_balance",
    }
