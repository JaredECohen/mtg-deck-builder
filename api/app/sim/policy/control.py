"""Control policy: develop mana, hold up interaction, deploy threats late."""

from __future__ import annotations

from app.sim.policy._common import Decision, castable, choose_land_to_play
from app.sim.state import CardInPlay, GameState


def control_policy(state: GameState) -> list[Decision]:
    decisions: list[Decision] = []
    land = choose_land_to_play(state)
    if land is not None:
        decisions.append(Decision(action="play_land", card=land))

    spendable = sum(1 for _ in state.untapped_lands())
    # Reserve 2 mana on opp turn for instant interaction if we have it.
    interaction_in_hand = any(
        c.profile.effect_vector.interaction_window == "instant"
        and (c.profile.role_weights.removal > 0 or c.profile.effect_vector.is_counterspell)
        for c in state.hand
    )
    reserved = 2 if interaction_in_hand and state.turn >= 2 else 0
    spendable_now = max(0, spendable - reserved)

    candidates = sorted(
        [c for c in state.hand if not c.is_land and castable(c, state)],
        key=lambda c: -_control_priority(c, state),
    )

    used_mana = 0
    for card in candidates:
        cost = int(card.profile.cost_vector.cmc)
        if used_mana + cost > spendable_now:
            continue
        decisions.append(Decision(action="cast", card=card))
        used_mana += cost

    return decisions


def _control_priority(card: CardInPlay, state: GameState) -> float:
    rw = card.profile.role_weights
    ev = card.profile.effect_vector
    score = rw.value_engine * 4 + rw.removal * 3 + rw.disruption * 3
    score += ev.cards_drawn * 1.5
    score += ev.board_impact * 0.5
    if ev.closes_game and state.turn >= 5:
        score += 3
    score -= card.profile.cost_vector.cmc * 0.1
    return score
