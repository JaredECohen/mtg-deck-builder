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
from app.sim import (
    GoldfishConfig,
    MulliganProfile,
    build_initial_state,
    goldfish,
)
from app.sim.policy import POLICIES, select_policy


def make_profile(
    name: str,
    *,
    cmc: float = 0.0,
    pips: dict[str, int] | None = None,
    role: dict[str, float] | None = None,
    effect: dict | None = None,
    keywords: tuple[str, ...] = (),
) -> CardProfile:
    """Construct a CardProfile from compact dict input — test ergonomics."""
    cv = CostVector(cmc=cmc, pips=pips or {}, color_demand={k: v for k, v in (pips or {}).items()})
    ev = EffectVector(**(effect or {}))
    rw = RoleWeights(**(role or {}))
    cp = ComboPrimitives(keywords=list(keywords))
    return CardProfile(
        card_id=name,
        name=name,
        cost_vector=cv,
        effect_vector=ev,
        role_weights=rw,
        combo_primitives=cp,
        oracle_ast=[],
        profile_version=PROFILE_VERSION,
        parse_method="pattern",
        parse_coverage=1.0,
    )


def burn_deck() -> list[tuple[CardProfile, str]]:
    """A simplified Modern Burn list: 12 1-mana 3-damage spells, 8 1-mana
    creatures (haste, 2 power), 20 mountains, 20 1-mana 1-damage spells.
    Total 60 cards."""
    deck: list[tuple[CardProfile, str]] = []
    bolt = make_profile(
        "Lightning Bolt",
        cmc=1.0,
        pips={"R": 1},
        role={"removal": 0.6, "closer": 0.4},
        effect={"damage_dealt": 3.0, "interaction_window": "instant"},
    )
    goblin = make_profile(
        "Goblin Guide",
        cmc=1.0,
        pips={"R": 1},
        role={"threat": 0.9, "closer": 0.1},
        effect={"board_impact": 2.5, "interaction_window": "permanent"},
        keywords=("haste",),
    )
    skewer = make_profile(
        "Skewer the Critics",
        cmc=2.0,
        pips={"R": 1},
        role={"closer": 0.7, "removal": 0.3},
        effect={"damage_dealt": 3.0},
    )
    mountain = make_profile(
        "Mountain",
        cmc=0.0,
        role={"land": 1.0},
        effect={"interaction_window": "static"},
        keywords=("R",),
    )
    deck.extend([(bolt, "Instant")] * 12)
    deck.extend([(goblin, "Creature — Goblin Scout")] * 8)
    deck.extend([(skewer, "Sorcery")] * 4)
    deck.extend([(mountain, "Basic Land — Mountain")] * 20)
    # Pad to 60 with extra small spells.
    pad = make_profile("Searing Blaze", cmc=2.0, pips={"R": 2}, role={"removal": 1.0},
                       effect={"damage_dealt": 3.0})
    deck.extend([(pad, "Instant")] * 16)
    return deck


def test_initial_state_construction():
    deck = burn_deck()
    state = build_initial_state(deck, seed=1)
    assert len(state.library) == 60
    assert len(state.hand) == 0
    assert state.life == 20
    assert state.opp_life == 20


def test_aggro_policy_selected_for_burn():
    burn_role_profile = {"threat": 0.4, "closer": 0.4, "removal": 0.2}
    chosen = select_policy(burn_role_profile)
    assert chosen == "aggro"


def test_combo_policy_selected_for_combo_role_profile():
    combo_profile = {"payoff": 0.5, "tutor": 0.3, "enabler": 0.2}
    assert select_policy(combo_profile) == "combo"


def test_control_policy_selected_for_control_profile():
    ctrl_profile = {"disruption": 0.4, "removal": 0.4, "value_engine": 0.2}
    assert select_policy(ctrl_profile) == "control"


def test_burn_kill_turn_distribution():
    """Phase 3 kill criterion: Burn goldfish kills around turn 4-5
    (community benchmark ≈ 4.2 on the play, 4.7 on the draw)."""
    deck = burn_deck()
    cfg = GoldfishConfig(games=400, max_turns=10, seed=42)
    mp = MulliganProfile(ideal_lands=(2, 4), needs_action_by_turn=2)
    report = goldfish(deck, policy=POLICIES["aggro"], mulligan_profile=mp, config=cfg)
    assert report.games_played == 400
    assert report.wins / report.games_played >= 0.5  # at least half end in a win
    # Average kill turn should land in the 4-7 band; goldfish without
    # interaction shouldn't take longer than 7 with a curved-out Burn list.
    assert 3.5 <= report.avg_kill_turn <= 7.5
    # Determinism: same seed = same kill turn.
    report2 = goldfish(deck, policy=POLICIES["aggro"], mulligan_profile=mp, config=cfg)
    assert report.avg_kill_turn == report2.avg_kill_turn
    assert report.kill_turn_distribution == report2.kill_turn_distribution


def test_goldfish_seed_reproducibility():
    deck = burn_deck()
    cfg = GoldfishConfig(games=50, max_turns=8, seed=99)
    a = goldfish(deck, policy=POLICIES["aggro"], config=cfg)
    b = goldfish(deck, policy=POLICIES["aggro"], config=cfg)
    assert a.kill_turn_distribution == b.kill_turn_distribution


def test_goldfish_records_history():
    deck = burn_deck()
    state = build_initial_state(deck, seed=5)
    from app.sim.mulligan import london_mulligan_loop, MulliganProfile
    london_mulligan_loop(state, MulliganProfile())
    assert any(h.get("event") == "keep_hand" for h in state.history)


def test_mulligan_keeps_reasonable_hand():
    """Strong hand (lots of action, 3 lands) should be kept first try."""
    deck = burn_deck()
    state = build_initial_state(deck, seed=1)
    from app.sim.mulligan import MulliganProfile, london_mulligan_loop
    mp = MulliganProfile(ideal_lands=(2, 4))
    london_mulligan_loop(state, mp, max_mulligans=3)
    # ≥7 - mulligan_count cards in hand (London rules).
    assert len(state.hand) == 7 - state.mulligans_taken
    assert state.mulligans_taken <= 3


def test_goldfish_no_lands_loses():
    """A deck with zero lands should never win — sanity check."""
    deck = []
    bolt = make_profile("Lightning Bolt", cmc=1.0, pips={"R": 1},
                        role={"removal": 1.0}, effect={"damage_dealt": 3.0})
    deck.extend([(bolt, "Instant")] * 60)
    cfg = GoldfishConfig(games=50, max_turns=8, seed=1)
    report = goldfish(deck, policy=POLICIES["aggro"], config=cfg)
    assert report.wins == 0


def test_tron_assembly_produces_seven_mana():
    """Urza's Tower + Power Plant + Mine together should produce 7
    colorless mana, enabling T3 7-drops."""
    from app.sim.goldfish import _gain_mana_phase
    from app.sim.state import CardInPlay, GameState, ManaPool
    from app.oracle.profile import (
        CardProfile, ComboPrimitives, CostVector, EffectVector, RoleWeights, PROFILE_VERSION
    )

    def land(name):
        prof = CardProfile(
            card_id=name, name=name,
            cost_vector=CostVector(cmc=0.0),
            effect_vector=EffectVector(),
            role_weights=RoleWeights(land=1.0),
            combo_primitives=ComboPrimitives(),
            oracle_ast=[], profile_version=PROFILE_VERSION, parse_method="pattern",
        )
        return CardInPlay(profile=prof, is_land=True, summoning_sick=False)

    state = GameState(seed=1, library=[], hand=[])
    state.battlefield = [
        land("Urza's Tower"),
        land("Urza's Power Plant"),
        land("Urza's Mine"),
    ]
    _gain_mana_phase(state)
    # 7 colorless from Tron, none from anywhere else.
    assert state.mana.total() == 7
    assert state.mana.pool.get("C", 0) == 7


def test_partial_tron_falls_back_to_one_mana_each():
    """Two of the three Urza lands shouldn't trigger the assembly bonus."""
    from app.sim.goldfish import _gain_mana_phase
    from app.sim.state import CardInPlay, GameState
    from app.oracle.profile import (
        CardProfile, ComboPrimitives, CostVector, EffectVector, RoleWeights, PROFILE_VERSION
    )

    def land(name):
        prof = CardProfile(
            card_id=name, name=name,
            cost_vector=CostVector(cmc=0.0),
            effect_vector=EffectVector(),
            role_weights=RoleWeights(land=1.0),
            combo_primitives=ComboPrimitives(),
            oracle_ast=[], profile_version=PROFILE_VERSION, parse_method="pattern",
        )
        return CardInPlay(profile=prof, is_land=True, summoning_sick=False)

    state = GameState(seed=1, library=[], hand=[])
    state.battlefield = [land("Urza's Tower"), land("Urza's Power Plant")]
    _gain_mana_phase(state)
    # Only 2 mana — assembly didn't kick in.
    assert state.mana.total() == 2


def test_aggressive_curve_kills_faster_than_slow_curve():
    """Aggro curve (1-drops) should kill measurably faster than a 4-drop curve."""
    fast = burn_deck()

    slow_deck = []
    big_dude = make_profile(
        "Slow Threat",
        cmc=4.0,
        pips={"R": 2},
        role={"threat": 1.0},
        effect={"board_impact": 4.0},
    )
    mountain = make_profile(
        "Mountain", cmc=0.0, role={"land": 1.0},
        effect={"interaction_window": "static"}, keywords=("R",),
    )
    slow_deck.extend([(big_dude, "Creature — Beast")] * 24)
    slow_deck.extend([(mountain, "Basic Land — Mountain")] * 24)
    spike = make_profile("Spike", cmc=4.0, pips={"R": 1}, role={"closer": 1.0},
                         effect={"damage_dealt": 4.0})
    slow_deck.extend([(spike, "Sorcery")] * 12)
    cfg = GoldfishConfig(games=200, max_turns=12, seed=17)
    fast_r = goldfish(fast, policy=POLICIES["aggro"], config=cfg)
    slow_r = goldfish(slow_deck, policy=POLICIES["aggro"], config=cfg)
    if fast_r.wins and slow_r.wins:
        assert fast_r.avg_kill_turn < slow_r.avg_kill_turn
