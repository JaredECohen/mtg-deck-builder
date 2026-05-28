"""Per-archetype goldfish benchmarks for the expanded multi-format meta.

The README previously noted that Living End, Yawgmoth, and Tron kill
turns were "produced but not asserted". These tests pin the simulator's
*calibrated* behavior for each meta archetype so a future engine change
that silently shifts an archetype's clock (or its grind profile) gets
caught.

Bands are intentionally wide — they assert the qualitative profile
(fast aggro vs. slow durdle vs. midrange tempo), not a brittle exact
number.
"""

from __future__ import annotations

import pytest

from app.sim import GoldfishConfig, goldfish
from app.sim.policy import POLICIES, select_policy
from app.sim.meta_archetypes import (
    amulet_titan,
    burn,
    izzet_phoenix_pio,
    living_end,
    mono_red_std,
    reanimator_leg,
    rug_delver_leg,
    tron,
    yawgmoth,
    format_meta,
)


def _role_profile(deck):
    p: dict[str, float] = {}
    for prof, _ in deck:
        for role, w in prof.role_weights.to_dict().items():
            p[role] = p.get(role, 0.0) + w
    return p


def _run(deck, *, games=200, max_turns=12, seed=7, starting_life=20):
    policy = POLICIES[select_policy(_role_profile(deck))]
    cfg = GoldfishConfig(games=games, max_turns=max_turns, seed=seed,
                         starting_life=starting_life)
    return goldfish(deck, policy=policy, config=cfg)


# --- fast aggro: kills early, wins often ------------------------------


@pytest.mark.parametrize("builder", [burn, mono_red_std])
def test_aggro_decks_kill_fast(builder):
    report = _run(builder())
    assert report.wins / report.games_played >= 0.5
    assert 4.0 <= report.avg_kill_turn <= 8.5


# --- tempo / midrange: wins but slower than aggro ---------------------


def test_izzet_phoenix_is_midrange_tempo():
    report = _run(izzet_phoenix_pio())
    assert report.wins / report.games_played >= 0.4
    assert report.avg_kill_turn >= 6.0


def test_living_end_wins_but_not_as_fast_as_burn():
    le = _run(living_end())
    bn = _run(burn())
    assert le.wins / le.games_played >= 0.3
    # Cascade-into-Living-End is modeled as a normal cast (~T5), so it's
    # slower than a curved Burn list in pure goldfish.
    assert le.avg_kill_turn > bn.avg_kill_turn


# --- slow combo / ramp durdles: low pure-goldfish win rate ------------
# These decks win in reality via a payoff (Ulamog, Yawgmoth engine,
# Primeval Titan) that the solitaire goldfish rarely converts to lethal.
# Asserting the *slow* profile documents that known modeling boundary.


@pytest.mark.parametrize("builder", [tron, yawgmoth, amulet_titan, reanimator_leg])
def test_slow_combo_durdles_are_slow_in_goldfish(builder):
    report = _run(builder())
    assert report.avg_kill_turn >= 9.0


# --- determinism: same seed → identical distribution ------------------


@pytest.mark.parametrize(
    "builder", [burn, mono_red_std, living_end, tron, rug_delver_leg]
)
def test_meta_goldfish_is_deterministic(builder):
    a = _run(builder(), games=60)
    b = _run(builder(), games=60)
    assert a.kill_turn_distribution == b.kill_turn_distribution
    assert a.avg_kill_turn == b.avg_kill_turn


# --- format meta selection --------------------------------------------


@pytest.mark.parametrize(
    "fmt,expected_label",
    [
        ("modern", "Burn"),
        ("standard", "Mono-Red Aggro"),
        ("pioneer", "Izzet Phoenix"),
        ("legacy", "RUG Delver"),
        ("commander", "Thoracle Combo"),
    ],
)
def test_format_meta_has_expected_archetypes(fmt, expected_label):
    meta = format_meta(fmt)
    assert expected_label in meta
    assert all(len(deck) >= 40 for deck in meta.values())


def test_unknown_format_falls_back_to_modern():
    assert format_meta("pauper") == format_meta("modern")
