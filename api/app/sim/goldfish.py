"""Goldfish simulator main loop.

Solitaire turn-by-turn play. Given a deck (list of CardProfile, type_line
pairs) and a policy, plays N games and returns a kill-turn distribution
plus per-turn diagnostics. Keeps the rules-engine surface intentionally
small: spells resolve immediately on cast (no opponent priority,
no targeting failures from state), creatures attack each turn for
``power`` damage, lands tap for one mana of any color in their identity.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Callable, Iterable

from app.oracle.profile import CardProfile
from app.sim.mulligan import MulliganProfile, london_mulligan_loop
from app.sim.policy._common import Decision
from app.sim.state import CardInPlay, GameState, ManaPool, build_initial_state


@dataclass
class GoldfishConfig:
    seed: int = 1729
    games: int = 1000
    max_turns: int = 12
    on_play: bool = True
    starting_life: int = 20


@dataclass
class GoldfishReport:
    games_played: int
    wins: int
    avg_kill_turn: float
    median_kill_turn: float
    p25_kill_turn: float
    p75_kill_turn: float
    kill_turn_distribution: dict[int, int]
    avg_engine_online_turn: float | None
    avg_mulligans: float
    avg_mana_left_unspent: float
    notes: list[str] = field(default_factory=list)


def goldfish(
    deck_records: list[tuple[CardProfile, str]],
    *,
    policy: Callable[[GameState], list[Decision]],
    mulligan_profile: MulliganProfile | None = None,
    config: GoldfishConfig | None = None,
) -> GoldfishReport:
    cfg = config or GoldfishConfig()
    mp = mulligan_profile or MulliganProfile()

    kill_turns: list[int] = []
    engine_turns: list[int] = []
    mulligans_taken: list[int] = []
    unspent_mana: list[float] = []

    for game_idx in range(cfg.games):
        state = build_initial_state(
            deck_records,
            seed=cfg.seed + game_idx,
            on_play=cfg.on_play,
            starting_life=cfg.starting_life,
        )
        london_mulligan_loop(state, mp)
        _play_game(state, policy=policy, max_turns=cfg.max_turns)
        if state.win_turn is not None:
            kill_turns.append(state.win_turn)
        if state.engine_online_turn is not None:
            engine_turns.append(state.engine_online_turn)
        mulligans_taken.append(state.mulligans_taken)
        # Sum of "spent mana left over each turn" is a tempo stat.
        leftover = sum(
            entry.get("unspent_mana", 0)
            for entry in state.history
            if entry.get("event") == "end_turn"
        )
        unspent_mana.append(leftover / max(1, state.turn))

    wins = len(kill_turns)
    if kill_turns:
        avg_kt = statistics.mean(kill_turns)
        med_kt = statistics.median(kill_turns)
        p25 = _percentile(kill_turns, 0.25)
        p75 = _percentile(kill_turns, 0.75)
    else:
        avg_kt = float(cfg.max_turns + 1)
        med_kt = float(cfg.max_turns + 1)
        p25 = float(cfg.max_turns + 1)
        p75 = float(cfg.max_turns + 1)

    distribution: dict[int, int] = {}
    for t in kill_turns:
        distribution[t] = distribution.get(t, 0) + 1
    notes: list[str] = []
    if wins / cfg.games < 0.4:
        notes.append(f"low goldfish win rate {wins / cfg.games:.0%} — deck under-powered or wrong policy")
    if avg_kt and avg_kt > 8:
        notes.append(f"slow kill ({avg_kt:.1f}) — consider lower curve / more reach")

    return GoldfishReport(
        games_played=cfg.games,
        wins=wins,
        avg_kill_turn=avg_kt,
        median_kill_turn=med_kt,
        p25_kill_turn=p25,
        p75_kill_turn=p75,
        kill_turn_distribution=distribution,
        avg_engine_online_turn=(statistics.mean(engine_turns) if engine_turns else None),
        avg_mulligans=statistics.mean(mulligans_taken) if mulligans_taken else 0.0,
        avg_mana_left_unspent=statistics.mean(unspent_mana) if unspent_mana else 0.0,
        notes=notes,
    )


def _play_game(state: GameState, *, policy, max_turns: int) -> None:
    while state.turn < max_turns:
        state.turn += 1
        _begin_turn(state)
        if state.is_game_over():
            return
        _draw(state)
        if state.is_game_over():
            return
        _untap_phase(state)
        _gain_mana_phase(state)
        decisions = policy(state)
        _resolve_decisions(state, decisions)
        _end_of_turn(state)
        if state.is_game_over():
            return


def _begin_turn(state: GameState) -> None:
    state.spells_cast_this_turn = 0
    state.cards_drawn_this_turn = 0
    state.storm_count = 0
    for c in state.creatures():
        c.summoning_sick = False
    state.mana.empty()


def _draw(state: GameState) -> None:
    if state.turn == 1 and state.on_play:
        return
    if not state.library:
        state.cards_drawn_this_turn += 1
        return  # losing condition handled by is_game_over
    state.hand.append(state.library.pop(0))
    state.cards_drawn_this_turn += 1


def _untap_phase(state: GameState) -> None:
    for c in state.battlefield:
        c.tapped = False
        # Clear "entered tapped this turn" — the land is now available
        # for mana on subsequent turns.
        c.entered_tapped_this_turn = False


def _gain_mana_phase(state: GameState) -> None:
    state.mana.empty()
    for land in state.untapped_lands():
        # Skip lands that entered tapped *this turn* — they don't tap
        # for mana the turn they came in.
        if land.entered_tapped_this_turn:
            continue
        # Approximate: each land taps for one mana of its produced colors.
        # Color choice is greedy — pick any color the land produces. The
        # mana-base solver handles the precise color question; goldfish
        # treats lands as "one generic mana, color-flagged."
        produced = _produced_colors(land)
        if produced:
            state.mana.add(produced[0], 1)
        else:
            state.mana.add("C", 1)


def _produced_colors(land: CardInPlay) -> list[str]:
    """Pull a guess at produced colors from the land's profile keywords/notes."""
    palette: list[str] = []
    blob = " ".join(land.profile.combo_primitives.keywords + (land.profile.notes or []))
    for color in ("W", "U", "B", "R", "G"):
        if color in blob:
            palette.append(color)
    return palette or ["C"]


def _resolve_decisions(state: GameState, decisions: list[Decision]) -> None:
    for d in decisions:
        if d.action == "play_land" and d.card is not None:
            _resolve_play_land(state, d.card)
        elif d.action == "cast" and d.card is not None:
            _resolve_cast(state, d.card)
        elif d.action == "attack" and d.card is not None:
            _resolve_attack(state, d.card)


def _resolve_play_land(state: GameState, card: CardInPlay) -> None:
    if card not in state.hand:
        return
    state.hand.remove(card)
    etb_tapped = _is_etb_tapped_land(card)
    card.tapped = etb_tapped
    card.entered_tapped_this_turn = etb_tapped
    state.battlefield.append(card)
    # Lands that ETB tapped don't add mana the turn they come in.
    if not etb_tapped:
        produced = _produced_colors(card)
        state.mana.add(produced[0], 1)
    state.log(event="play_land", card=card.name, etb_tapped=etb_tapped)


def _is_etb_tapped_land(card: CardInPlay) -> bool:
    """Heuristic detection of ETB-tapped lands.

    Reads the parsed oracle AST (Phase-1 output) for "enters tapped"
    text. Conservative — basic lands and untapped duals should always
    return False; tap-lands and conditional ETBs (checklands, fastlands)
    should return True. The matchup/goldfish simulators only need a
    sane *expectation*, not deterministic correctness on every card.
    """
    if not card.is_land:
        return False
    profile = card.profile
    notes = " ".join(profile.notes or []).lower()
    if "tapped" in notes and "untapped" not in notes:
        return True
    for effect in profile.oracle_ast or []:
        text = (effect.text or "").lower()
        if "enters tapped" in text or "enters the battlefield tapped" in text:
            # Conditional taps ("enters tapped unless ...") are still
            # *more often than not* tapped — return True to avoid the
            # solver overestimating mana availability.
            return True
    return False


def _resolve_cast(state: GameState, card: CardInPlay) -> None:
    cv = card.profile.cost_vector
    cmc = int(cv.cmc)
    pips = {k: v for k, v in cv.pips.items() if k in {"W", "U", "B", "R", "G"}}
    generic = max(0, cmc - sum(pips.values()))
    if not state.mana.pay(generic, pips):
        return
    if card not in state.hand:
        return
    state.hand.remove(card)
    state.spells_cast_this_turn += 1
    state.storm_count += 1
    _resolve_card_effects(state, card)
    if card.is_creature or card.is_planeswalker or "enchantment" in (card.profile.notes or []):
        card.summoning_sick = card.is_creature
        state.battlefield.append(card)
    else:
        state.graveyard.append(card)
    state.log(event="cast", card=card.name, cmc=cmc, storm=state.storm_count)


def _resolve_card_effects(state: GameState, card: CardInPlay) -> None:
    ev = card.profile.effect_vector
    if ev.cards_drawn:
        for _ in range(int(ev.cards_drawn)):
            if state.library:
                state.hand.append(state.library.pop(0))
                state.cards_drawn_this_turn += 1
    if ev.damage_dealt:
        state.opp_life -= int(ev.damage_dealt)
    if ev.life_gained:
        state.life += int(ev.life_gained)
    if ev.life_lost:
        state.life -= int(ev.life_lost)
    if ev.creatures_made:
        for i in range(int(ev.creatures_made)):
            token = CardInPlay(
                profile=card.profile,
                is_creature=True,
                summoning_sick=False if "haste" in card.profile.combo_primitives.keywords else True,
            )
            state.battlefield.append(token)
    if ev.mana_produced:
        # Deferred production (treasure tokens, etc.); add to current pool.
        state.mana.add("C", int(ev.mana_produced))
    if ev.closes_game and state.engine_online_turn is None:
        state.engine_online_turn = state.turn


def _resolve_attack(state: GameState, card: CardInPlay) -> None:
    if card.tapped or card.summoning_sick:
        return
    power = _creature_power(card)
    state.opp_life -= power
    card.tapped = True
    state.log(event="attack", card=card.name, power=power, opp_life=state.opp_life)


def _creature_power(card: CardInPlay) -> int:
    """Best-guess power: from board_impact (which embeds P+T)."""
    bi = card.profile.effect_vector.board_impact
    return max(1, int(round(bi / 1.4)))


def _end_of_turn(state: GameState) -> None:
    state.log(event="end_turn", unspent_mana=state.mana.total())


def _percentile(values: Iterable[int], pct: float) -> float:
    arr = sorted(values)
    if not arr:
        return 0.0
    k = (len(arr) - 1) * pct
    f = int(k)
    c = min(f + 1, len(arr) - 1)
    if f == c:
        return float(arr[f])
    return arr[f] + (arr[c] - arr[f]) * (k - f)
