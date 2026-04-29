"""Midrange policy: trade efficiently, accumulate value, deploy threats."""

from __future__ import annotations

from app.sim.policy._common import Decision, castable, choose_land_to_play, plan_attacks
from app.sim.state import CardInPlay, GameState


def midrange_policy(state: GameState) -> list[Decision]:
    decisions: list[Decision] = []
    land = choose_land_to_play(state)
    if land is not None:
        decisions.append(Decision(action="play_land", card=land))

    spendable = sum(1 for _ in state.untapped_lands())
    candidates = sorted(
        [c for c in state.hand if not c.is_land and castable(c, state)],
        key=lambda c: -_midrange_priority(c, state),
    )

    used_mana = 0
    for card in candidates:
        cost = int(card.profile.cost_vector.cmc)
        if used_mana + cost > spendable:
            continue
        decisions.append(Decision(action="cast", card=card))
        used_mana += cost

    decisions.extend(plan_attacks(state))
    return decisions


def _midrange_priority(card: CardInPlay, state: GameState) -> float:
    rw = card.profile.role_weights
    ev = card.profile.effect_vector
    score = rw.threat * 3 + rw.value_engine * 3 + rw.removal * 2 + rw.fixer * 1.5
    score += ev.cards_drawn * 1.0
    score += ev.board_impact * 0.7
    # Midrange wants curve coverage — slight bonus for cards matching our turn.
    cmc = int(card.profile.cost_vector.cmc)
    if cmc == state.turn:
        score += 1.0
    return score
