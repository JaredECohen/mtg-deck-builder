"""Aggro policy: curve out, deal damage, never lose tempo."""

from __future__ import annotations

from app.sim.state import CardInPlay, GameState

from app.sim.policy._common import (
    Decision,
    castable,
    choose_land_to_play,
    plan_attacks,
)


def aggro_policy(state: GameState) -> list[Decision]:
    decisions: list[Decision] = []
    land = choose_land_to_play(state)
    if land is not None:
        decisions.append(Decision(action="play_land", card=land))

    spendable_mana = sum(1 for _ in state.untapped_lands()) + (
        1 if land is not None and not _enters_tapped(land) else 0
    )

    castable_cards = sorted(
        [c for c in state.hand if not c.is_land and castable(c, state, extra_mana=spendable_mana - len(state.untapped_lands()))],
        key=lambda c: -_aggro_priority(c),
    )

    used_mana = 0
    for card in castable_cards:
        cost = int(card.profile.cost_vector.cmc)
        if used_mana + cost > spendable_mana:
            continue
        decisions.append(Decision(action="cast", card=card))
        used_mana += cost

    decisions.extend(plan_attacks(state))
    return decisions


def _enters_tapped(card: CardInPlay) -> bool:
    return False  # The simulator handles tap state; aggro tries untapped first.


def _aggro_priority(card: CardInPlay) -> float:
    """Higher = play first. Aggro favors low-CMC threats and burn."""
    cmc = card.profile.cost_vector.cmc
    rw = card.profile.role_weights
    base = rw.threat * 5 + rw.closer * 4 + rw.removal * 1.5
    speed = 4.0 - cmc  # 1-drops first, 4-drops last
    keywords = card.profile.combo_primitives.keywords
    if "haste" in keywords:
        base += 1.5
    if "prowess" in keywords:
        base += 1.0
    if "flying" in keywords:
        base += 0.5
    return base + speed
