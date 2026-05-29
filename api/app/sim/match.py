"""Two-player matchup simulator.

Simplifying assumptions:

* Both players run their goldfish independently each turn.
* Each player's removal/counterspells reduce the *opposing* player's
  damage output and threat density.
* Damage accumulates against the opposing life total — first to ≤ 0
  loses; the other wins.
* Combat blocking is approximated: defender allocates power to
  block the highest incoming-power attacker first; remaining power
  goes through to face.
* Counterspells delay an opposing spell by 1 turn (probabilistic).

This is *not* a full rules engine. It's the cheapest simulator that
produces a believable matchup-win-rate signal — which is all the
optimizer's fitness function and the critic's R3 rubric need.

Determinism: same (deck_a, deck_b, seed) → same outcome. Required
for the critic loop to reproduce evidence.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Callable

from app.oracle.profile import CardProfile
from app.sim.goldfish import _gain_mana_phase, _resolve_decisions, _untap_phase
from app.sim.mulligan import MulliganProfile, london_mulligan_loop
from app.sim.policy import POLICIES, select_policy
from app.sim.policy._common import Decision
from app.sim.state import GameState, build_initial_state


@dataclass
class MatchConfig:
    games: int = 200
    max_turns: int = 12
    seed: int = 1729
    starting_life: int = 20
    record_traces: bool = False
    format_id: str = "modern"
    # Per-side format override. When None, both sides use ``format_id``
    # — but cross-format matchups (e.g. Commander candidate vs Modern
    # meta opponents) need separate mulligan profiles for each side.
    opponent_format_id: str | None = None


@dataclass
class MatchResult:
    games_played: int
    wins_a: int
    wins_b: int
    draws: int
    avg_game_length: float
    win_rate_a: float
    avg_life_a: float
    avg_life_b: float
    notes: list[str] = field(default_factory=list)


@dataclass
class MatchupMatrix:
    """Win rates for ``candidate`` deck against each opponent."""

    by_opponent: dict[str, float] = field(default_factory=dict)
    avg_winrate: float = 0.0
    weakest_matchup: str | None = None
    weakest_winrate: float = 1.0
    strongest_matchup: str | None = None
    strongest_winrate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "by_opponent": dict(self.by_opponent),
            "avg_winrate": self.avg_winrate,
            "weakest_matchup": self.weakest_matchup,
            "weakest_winrate": self.weakest_winrate,
            "strongest_matchup": self.strongest_matchup,
            "strongest_winrate": self.strongest_winrate,
        }


def simulate_match(
    deck_a: list[tuple[CardProfile, str]],
    deck_b: list[tuple[CardProfile, str]],
    *,
    policy_a: Callable[[GameState], list[Decision]] | None = None,
    policy_b: Callable[[GameState], list[Decision]] | None = None,
    mulligan_a: MulliganProfile | None = None,
    mulligan_b: MulliganProfile | None = None,
    config: MatchConfig | None = None,
) -> MatchResult:
    cfg = config or MatchConfig()
    pa = policy_a or _pick_policy(deck_a)
    pb = policy_b or _pick_policy(deck_b)
    # Player A is always the candidate; player B is the opponent. When
    # cross-format (e.g. Commander candidate vs Modern meta deck), each
    # side mulligans against its own format's defaults.
    opp_fmt = cfg.opponent_format_id or cfg.format_id
    mp_a = mulligan_a or _format_mulligan_profile(cfg.format_id)
    mp_b = mulligan_b or _format_mulligan_profile(opp_fmt)

    wins_a = wins_b = draws = 0
    game_lengths: list[int] = []
    final_life_a: list[int] = []
    final_life_b: list[int] = []

    for game_idx in range(cfg.games):
        seed = cfg.seed + game_idx
        # Alternate who's on the play to neutralize the bias.
        a_on_play = (game_idx % 2 == 0)
        state_a = build_initial_state(deck_a, seed=seed, on_play=a_on_play,
                                       starting_life=cfg.starting_life)
        state_b = build_initial_state(deck_b, seed=seed + 100000, on_play=not a_on_play,
                                       starting_life=cfg.starting_life)
        london_mulligan_loop(state_a, mp_a)
        london_mulligan_loop(state_b, mp_b)

        winner = _play_two_player(state_a, state_b, pa, pb, cfg.max_turns)
        if winner == "a":
            wins_a += 1
        elif winner == "b":
            wins_b += 1
        else:
            draws += 1
        game_lengths.append(max(state_a.turn, state_b.turn))
        final_life_a.append(state_a.opp_life)  # opp_life from a's perspective = b's life
        final_life_b.append(state_b.opp_life)

    games = max(1, cfg.games)
    win_rate_a = wins_a / games
    return MatchResult(
        games_played=cfg.games,
        wins_a=wins_a,
        wins_b=wins_b,
        draws=draws,
        avg_game_length=statistics.mean(game_lengths) if game_lengths else 0.0,
        win_rate_a=win_rate_a,
        avg_life_a=statistics.mean(final_life_a) if final_life_a else 0.0,
        avg_life_b=statistics.mean(final_life_b) if final_life_b else 0.0,
    )


def build_matchup_matrix(
    candidate_deck: list[tuple[CardProfile, str]],
    *,
    opponents: dict[str, list[tuple[CardProfile, str]]] | None = None,
    config: MatchConfig | None = None,
    opponent_formats: dict[str, str] | None = None,
) -> MatchupMatrix:
    """Run the candidate against every meta opponent; build a matrix.

    If ``opponents`` is None, the opponent set is selected by the
    candidate's own format (``config.format_id``) via
    :func:`meta_archetypes.format_meta` — so a Standard deck is graded
    against the Standard meta, a Commander deck against the Commander
    meta, and so on. ``opponent_formats`` (label -> format_id) lets each
    opponent mulligan with its native format's profile — important for
    cross-format matchups (Commander candidate vs Modern meta decks).
    """
    from app.sim.meta_archetypes import (
        META_DECK_FORMATS,
        format_meta,
        format_meta_formats,
    )

    fmt_id = (config or MatchConfig()).format_id
    if opponents is None:
        opponents = format_meta(fmt_id)
        if opponent_formats is None:
            opponent_formats = format_meta_formats(fmt_id)
    if opponent_formats is None:
        opponent_formats = META_DECK_FORMATS
    matrix = MatchupMatrix()
    by_opponent: dict[str, float] = {}
    for label, opp_deck in opponents.items():
        opp_fmt = opponent_formats.get(label)
        run_cfg = config
        if opp_fmt is not None:
            from dataclasses import replace
            base_cfg = config or MatchConfig()
            run_cfg = replace(base_cfg, opponent_format_id=opp_fmt)
        result = simulate_match(candidate_deck, opp_deck, config=run_cfg)
        by_opponent[label] = result.win_rate_a
    matrix.by_opponent = by_opponent
    if by_opponent:
        matrix.avg_winrate = statistics.mean(by_opponent.values())
        matrix.weakest_matchup = min(by_opponent, key=by_opponent.get)
        matrix.weakest_winrate = by_opponent[matrix.weakest_matchup]
        matrix.strongest_matchup = max(by_opponent, key=by_opponent.get)
        matrix.strongest_winrate = by_opponent[matrix.strongest_matchup]
    return matrix


# --- internals ---------------------------------------------------------


def _pick_policy(deck: list[tuple[CardProfile, str]]):
    role_profile: dict[str, float] = {}
    for profile, _ in deck:
        for role, weight in profile.role_weights.to_dict().items():
            role_profile[role] = role_profile.get(role, 0) + weight
    return POLICIES[select_policy(role_profile)]


def _format_mulligan_profile(format_id: str) -> MulliganProfile:
    """Pull a default MulliganProfile from format config so matchup
    games for Commander mulligan with (3-5 lands), not Modern's
    (2-5)."""
    try:
        from app.optimizer.format_config import get_format_config
        fmt = get_format_config(format_id)
        return MulliganProfile(
            ideal_lands=fmt.mulligan_ideal_lands,
            needs_action_by_turn=fmt.needs_action_by_turn,
        )
    except (ImportError, ValueError):
        return MulliganProfile()


def _play_two_player(
    state_a: GameState,
    state_b: GameState,
    policy_a,
    policy_b,
    max_turns: int,
) -> str:
    """Run one match. Returns "a", "b", or "draw"."""
    # Player on the play goes first.
    first, first_policy, first_label = (
        (state_a, policy_a, "a") if state_a.on_play else (state_b, policy_b, "b")
    )
    second, second_policy, second_label = (
        (state_b, policy_b, "b") if state_a.on_play else (state_a, policy_a, "a")
    )

    for round_idx in range(max_turns):
        # First player's turn.
        winner = _take_turn(first, second, first_policy, second_policy, on_play_round=(round_idx == 0))
        if winner is not None:
            return first_label if winner == "self" else second_label
        # Second player's turn.
        winner = _take_turn(second, first, second_policy, first_policy, on_play_round=False)
        if winner is not None:
            return second_label if winner == "self" else first_label

    # Time-out: whichever player has more remaining damage potential wins.
    a_pressure = _board_pressure(state_a)
    b_pressure = _board_pressure(state_b)
    if a_pressure > b_pressure + 0.5:
        return "a"
    if b_pressure > a_pressure + 0.5:
        return "b"
    return "draw"


def _take_turn(
    actor: GameState,
    opponent: GameState,
    actor_policy,
    opp_policy,
    *,
    on_play_round: bool,
) -> str | None:
    """Resolve one player's turn. Returns "self" if actor wins this turn,
    "opp" if actor's library is empty on draw, or None.

    Order:
      1. Begin-turn state reset.
      2. Draw (skipped on T1 of the on-the-play player).
      3. Untap + mana.
      4. Policy emits decisions; we resolve casts only (combat handled
         separately to avoid the goldfish's "all damage hits face"
         shortcut).
      5. Combat: attackers tap, blockers absorb power, leftover
         goes face.
      6. Apply spell damage (captured via opp_life delta) + face combat
         damage to opponent.life.
      7. Opponent's instant interaction removes one threat.
    """
    actor.turn += 1
    actor.spells_cast_this_turn = 0
    actor.cards_drawn_this_turn = 0
    actor.storm_count = 0
    for c in actor.creatures():
        c.summoning_sick = False
    actor.mana.empty()

    if not (actor.turn == 1 and actor.on_play and on_play_round):
        if actor.library:
            actor.hand.append(actor.library.pop(0))
            actor.cards_drawn_this_turn += 1
        else:
            return "opp"

    _untap_phase(actor)
    _gain_mana_phase(actor)

    # Reset opp_life so we can read this-turn spell damage as a delta.
    starting_life = getattr(actor, "starting_life", 20)
    actor.opp_life = starting_life

    decisions = actor_policy(actor)
    spell_decisions = [d for d in decisions if d.action != "attack"]
    attack_decisions = [d for d in decisions if d.action == "attack"]
    _resolve_decisions(actor, spell_decisions)
    spell_damage = max(0, starting_life - actor.opp_life)

    # Combat phase.
    attackers: list = []
    for d in attack_decisions:
        c = d.card
        if c is None or c.tapped or c.summoning_sick:
            continue
        if "defender" in c.profile.combo_primitives.keywords:
            continue
        attackers.append(c)
        c.tapped = True
    creature_pressure = sum(_creature_power(a) for a in attackers)

    blockers = [
        c for c in opponent.creatures()
        if "defender" not in c.profile.combo_primitives.keywords
    ]
    creature_dmg_absorbed = 0.0
    blocker_kills: list = []
    attacker_kills: list = []
    remaining = creature_pressure
    # Greedy: biggest blockers stop biggest pressure first; if blocker
    # power ≥ attacker power, both die (mutual trade); otherwise blocker
    # absorbs partially.
    sorted_attackers = sorted(attackers, key=lambda a: -_creature_power(a))
    sorted_blockers = sorted(blockers, key=lambda c: -_creature_power(c))
    bi = 0
    for atk in sorted_attackers:
        if bi >= len(sorted_blockers):
            break
        blk = sorted_blockers[bi]
        bi += 1
        ap = _creature_power(atk)
        bp = _creature_power(blk)
        absorbed = min(remaining, bp)
        remaining -= absorbed
        creature_dmg_absorbed += absorbed
        # Trade: if blocker's power ≥ attacker's power, attacker dies.
        if bp >= ap:
            attacker_kills.append(atk)
        if ap >= bp:
            blocker_kills.append(blk)
    face_damage = max(0.0, remaining)

    # Apply combat-derived deaths.
    for atk in attacker_kills:
        if atk in actor.battlefield:
            actor.battlefield.remove(atk)
            actor.graveyard.append(atk)
    for blk in blocker_kills:
        if blk in opponent.battlefield:
            opponent.battlefield.remove(blk)
            opponent.graveyard.append(blk)

    opponent.life -= int(round(face_damage + spell_damage))

    _apply_opponent_instant_interaction(actor, opponent)

    if opponent.life <= 0:
        return "self"
    if actor.life <= 0:
        return "opp"
    return None


def _creature_power(card) -> float:
    return max(1.0, card.profile.effect_vector.board_impact / 1.4)


def _apply_opponent_instant_interaction(actor: GameState, opponent: GameState) -> None:
    """Probabilistic removal: opponent's hand has interaction with some
    expected impact on the actor's threats. Spends one untapped land
    of the opponent's per use — without that, opponent gets unlimited
    free removal."""
    interaction_in_hand = [
        c for c in opponent.hand
        if c.profile.role_weights.removal >= 0.3
        or c.profile.effect_vector.is_counterspell
    ]
    if not interaction_in_hand or not actor.creatures():
        return
    untapped = opponent.untapped_lands()
    interaction_card = interaction_in_hand[0]
    cost = max(1, int(interaction_card.profile.cost_vector.cmc) or 1)
    if len(untapped) < cost:
        return  # Can't pay — opponent eats damage this turn.
    biggest = max(actor.creatures(), key=_creature_power)
    if _creature_power(biggest) < 2:
        return  # Not worth the interaction — save mana for next turn.
    actor.battlefield.remove(biggest)
    actor.graveyard.append(biggest)
    # Tap exactly enough lands to pay for the spell.
    for land in untapped[:cost]:
        land.tapped = True
    opponent.hand.remove(interaction_card)
    opponent.graveyard.append(interaction_card)


def _board_pressure(state: GameState) -> float:
    return sum(_creature_power(c) for c in state.creatures())
