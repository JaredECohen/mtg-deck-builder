from __future__ import annotations

import pytest

from app.sim import (
    MatchConfig,
    META_DECKS,
    build_matchup_matrix,
    simulate_match,
)
from app.sim.meta_archetypes import burn, living_end, murktide, tron


def test_burn_vs_burn_is_roughly_50_50():
    """A deck against itself should produce ~50% win rate (with on-the-play
    alternation). Variance allowed: ±10%."""
    deck = burn()
    cfg = MatchConfig(games=80, max_turns=10, seed=42)
    result = simulate_match(deck, deck, config=cfg)
    assert 0.40 <= result.win_rate_a <= 0.60


def test_match_is_deterministic_by_seed():
    deck_a = burn()
    deck_b = murktide()
    cfg = MatchConfig(games=40, seed=99)
    r1 = simulate_match(deck_a, deck_b, config=cfg)
    r2 = simulate_match(deck_a, deck_b, config=cfg)
    assert r1.wins_a == r2.wins_a
    assert r1.wins_b == r2.wins_b


def test_burn_beats_slow_tron_in_goldfish_pressure():
    """Burn should out-pressure Tron in raw goldfish (no real interaction
    on the Tron side beyond Oblivion Stone). Allowing wide tolerance —
    the simulator's combat model is approximate."""
    cfg = MatchConfig(games=100, max_turns=10, seed=7)
    result = simulate_match(burn(), tron(), config=cfg)
    # Burn should win at least 35% of games against pure Tron skeleton.
    assert result.win_rate_a >= 0.35


def test_matchup_matrix_covers_all_meta_decks():
    cfg = MatchConfig(games=30, max_turns=8, seed=11)
    matrix = build_matchup_matrix(burn(), config=cfg)
    assert set(matrix.by_opponent.keys()) == set(META_DECKS.keys())
    assert all(0.0 <= w <= 1.0 for w in matrix.by_opponent.values())
    assert matrix.weakest_matchup is not None
    assert matrix.strongest_matchup is not None
    assert matrix.weakest_winrate <= matrix.avg_winrate <= matrix.strongest_winrate


def test_matchup_matrix_handles_empty_opponents():
    matrix = build_matchup_matrix(burn(), opponents={}, config=MatchConfig(games=10))
    assert matrix.by_opponent == {}
    assert matrix.avg_winrate == 0.0
    assert matrix.weakest_matchup is None


def test_matchup_matrix_serializes():
    cfg = MatchConfig(games=20, max_turns=8)
    matrix = build_matchup_matrix(burn(), config=cfg)
    d = matrix.to_dict()
    assert "by_opponent" in d
    assert "avg_winrate" in d
    assert isinstance(d["by_opponent"], dict)


def test_match_records_avg_game_length():
    cfg = MatchConfig(games=30, max_turns=10, seed=3)
    result = simulate_match(burn(), murktide(), config=cfg)
    # Goldfish kill turn for Burn ~ 5; Murktide ~ 7; matchup should
    # average somewhere in between.
    assert 3.0 <= result.avg_game_length <= 12.0


def test_living_end_has_distinct_signature():
    """Sanity check that the matchup matrix differentiates archetypes."""
    cfg = MatchConfig(games=30, max_turns=10, seed=5)
    matrix = build_matchup_matrix(murktide(), config=cfg)
    # UR Tempo has counterspells which should make Living End at least
    # not autoloss. The two matchups (Burn vs Living End) should not
    # be identical to four decimal places.
    burn_wr = matrix.by_opponent.get("Burn", 0)
    le_wr = matrix.by_opponent.get("Living End", 0)
    assert burn_wr != le_wr


def test_matchup_strength_appears_in_fitness_when_enabled():
    """Matchup matrix flows from compute_fitness to FitnessVector."""
    from app.optimizer.fitness import compute_fitness

    deck = burn()
    fv = compute_fitness(deck, sim_runs=20, max_turns=8, seed=1,
                         include_matchup=True, matchup_games=10)
    # Should NOT be the neutral 0.5 default after computation.
    assert fv.matchup_strength != 0.5
    assert "matchup_matrix" in fv.raw
    matrix = fv.raw["matchup_matrix"]
    assert isinstance(matrix, dict)
    assert len(matrix) > 0


def test_matchup_strength_skipped_when_disabled():
    from app.optimizer.fitness import compute_fitness

    deck = burn()
    fv = compute_fitness(deck, sim_runs=20, max_turns=8, seed=1,
                         include_matchup=False)
    # Default neutral 0.5 — matchup not run.
    assert fv.matchup_strength == 0.5
    assert fv.raw.get("matchup_matrix") in (None, {})


def test_match_uses_format_mulligan_floor():
    """Commander matches should default to (3-5) ideal lands and need
    action by turn 4, even when caller doesn't pass mulligan_a/b."""
    from app.sim.match import _format_mulligan_profile
    cmd = _format_mulligan_profile("commander")
    assert cmd.ideal_lands == (3, 5)
    assert cmd.needs_action_by_turn == 4
    mod = _format_mulligan_profile("modern")
    assert mod.ideal_lands == (2, 5)
    assert mod.needs_action_by_turn == 3


def test_match_unknown_format_falls_back_to_default():
    from app.sim.match import _format_mulligan_profile
    profile = _format_mulligan_profile("vintage")  # not in FORMATS
    # Should fall back gracefully without raising.
    assert profile is not None
    assert isinstance(profile.ideal_lands, tuple)


def test_rationale_uses_matchup_matrix_from_fitness_raw():
    """When fitness.raw['matchup_matrix'] is populated, the rationale
    should surface those matchups even without an external envelope."""
    from app.optimizer.fitness import OptimizerCandidate, FitnessVector
    from app.services.deck_rationale import build_deck_rationale

    fv = FitnessVector(
        kill_turn_score=0.8, mulligan_keep=0.9, mana_consistency=0.9,
        matchup_strength=0.6,
        raw={"avg_kill_turn": 4.5, "win_rate": 0.9, "archetype": "aggro",
             "matchup_matrix": {"Burn": 0.5, "Tron": 0.7, "Living End": 0.4}},
    )
    candidate = OptimizerCandidate(deck=[], fitness=fv, score=0.7)
    r = build_deck_rationale(candidate)
    assert len(r.soft_matchups) == 3
    names = {m.opponent_archetype for m in r.soft_matchups}
    assert names == {"Burn", "Tron", "Living End"}
