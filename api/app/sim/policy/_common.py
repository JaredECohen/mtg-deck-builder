"""Shared decision primitives for policies."""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.state import CardInPlay, GameState


@dataclass
class Decision:
    action: str  # "play_land", "cast", "attack", "activate", "pass"
    card: CardInPlay | None = None
    target: str | None = None
    note: str = ""


def choose_land_to_play(state: GameState) -> CardInPlay | None:
    """Pick the best land in hand for this turn.

    Heuristics: prefer untapped lands turn ≤ 2, basics for color
    consistency, and lands that produce a color we *need* to cast a
    held spell.
    """
    lands = [c for c in state.hand if c.is_land]
    if not lands:
        return None
    needed_colors: set[str] = set()
    for c in state.hand:
        if c.is_land:
            continue
        for color, count in c.profile.cost_vector.pips.items():
            if color in {"W", "U", "B", "R", "G"} and count > 0:
                needed_colors.add(color)

    def score(land: CardInPlay) -> tuple[int, int, int]:
        type_l = (land.profile.cost_vector.alt_costs or [])
        produces_needed = 1 if any(p in needed_colors for p in _produces(land)) else 0
        # Crude: lands flagged as "tapped" or with high etb_tapped_prior get
        # deprioritized turn 1 / 2.
        early_turn_penalty = (
            -1
            if state.turn <= 2 and "tapped" in (land.profile.notes or [])
            else 0
        )
        return (produces_needed, early_turn_penalty, -int(land.profile.cost_vector.cmc))

    return max(lands, key=score)


def _produces(land: CardInPlay) -> set[str]:
    """Crude color-production inference from land profile."""
    colors: set[str] = set()
    text_blob = " ".join(land.profile.combo_primitives.keywords)
    for color in ("W", "U", "B", "R", "G"):
        if color in text_blob:
            colors.add(color)
    return colors


def castable(card: CardInPlay, state: GameState, extra_mana: int = 0) -> bool:
    """Can we cast this card given current mana availability?"""
    if card.is_land:
        return False
    cv = card.profile.cost_vector
    cmc = int(cv.cmc)
    if cmc <= 0:
        return True
    available_mana = sum(1 for _ in state.untapped_lands()) + extra_mana
    if available_mana < cmc:
        return False
    return True


def plan_attacks(state: GameState) -> list[Decision]:
    """Tap untapped, non-summoning-sick creatures to attack."""
    out: list[Decision] = []
    for creature in state.creatures():
        if creature.tapped or creature.summoning_sick:
            continue
        if "defender" in creature.profile.combo_primitives.keywords:
            continue
        out.append(Decision(action="attack", card=creature))
    return out
