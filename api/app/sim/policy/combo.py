"""Combo policy: assemble pieces, dig with cantrips, deploy payoff."""

from __future__ import annotations

from app.sim.policy._common import Decision, castable, choose_land_to_play
from app.sim.state import CardInPlay, GameState


def combo_policy(state: GameState) -> list[Decision]:
    decisions: list[Decision] = []
    land = choose_land_to_play(state)
    if land is not None:
        decisions.append(Decision(action="play_land", card=land))

    # Combo decks prioritize: tutors > cantrips > enablers > payoff.
    spendable = sum(1 for _ in state.untapped_lands())
    candidates = sorted(
        [c for c in state.hand if not c.is_land and castable(c, state)],
        key=lambda c: -_combo_priority(c),
    )

    used_mana = 0
    for card in candidates:
        cost = int(card.profile.cost_vector.cmc)
        if used_mana + cost > spendable:
            continue
        decisions.append(Decision(action="cast", card=card))
        used_mana += cost
        if card.profile.effect_vector.closes_game:
            break  # Pop the win, stop spending mana on lesser things.

    return decisions


def _combo_priority(card: CardInPlay) -> float:
    rw = card.profile.role_weights
    ev = card.profile.effect_vector
    score = rw.tutor * 6 + rw.payoff * 4 + rw.enabler * 3 + rw.value_engine * 2
    if ev.is_combo_payoff:
        score += 5
    if ev.is_tutor:
        score += 4
    score += ev.cards_drawn * 1.0
    score += ev.mana_produced * 1.5
    score -= card.profile.cost_vector.cmc * 0.3  # cheap pieces first
    return score
