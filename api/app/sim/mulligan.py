"""London-mulligan + scry hand evaluator.

Given a candidate opening hand, decide whether to keep or mulligan.
The decision uses a multi-factor heuristic that mirrors how a strong
player evaluates a hand:

* land count vs ideal range for the deck's curve
* presence of an early action (1- or 2-drop)
* presence of a critical card (depending on deck role profile)
* mulligan count (London: each mulligan puts a card on the bottom,
  so successive mulligans should be tighter on quality)
"""

from __future__ import annotations

from dataclasses import dataclass

from app.sim.state import CardInPlay, GameState


@dataclass
class MulliganProfile:
    """How a deck wants to filter opening hands.

    ``ideal_lands`` is the (lo, hi) range of acceptable land counts in
    the opening 7. ``needs_action_by_turn`` says when an early threat
    or interaction must be castable. ``critical_card_names`` lets a
    combo deck demand a specific piece (e.g., Living End needs a
    suspendable cascade card).
    """

    ideal_lands: tuple[int, int] = (2, 5)
    needs_action_by_turn: int = 3
    critical_card_names: tuple[str, ...] = ()
    keep_threshold: float = 0.55


def hand_quality(hand: list[CardInPlay], profile: MulliganProfile, mulligan_count: int) -> float:
    """Return a 0–1 score; higher = keep."""
    if not hand:
        return 0.0
    lands = sum(1 for c in hand if c.is_land)
    nonlands = len(hand) - lands
    score = 1.0
    lo, hi = profile.ideal_lands
    if lands < lo or lands > hi:
        score -= 0.35
    if lands == 0 or lands == len(hand):
        score -= 0.4
    cmcs = sorted(int(c.profile.cost_vector.cmc) for c in hand if not c.is_land)
    if cmcs and cmcs[0] > profile.needs_action_by_turn:
        score -= 0.2
    if nonlands == 0:
        score -= 0.3
    if profile.critical_card_names:
        if not any(c.name in profile.critical_card_names for c in hand):
            score -= 0.25
    # Successive mulligans should clear the bar more confidently.
    score += 0.05 * mulligan_count
    return max(0.0, min(1.0, score))


def london_mulligan_loop(
    state: GameState,
    profile: MulliganProfile,
    *,
    max_mulligans: int = 3,
) -> None:
    """Mutate ``state`` into a kept opening hand using London mulligan.

    Each mulligan: draw 7, evaluate; if not keeping, shuffle back and
    bottom one card per mulligan taken. After bottoming, the simulator
    proceeds with the kept hand of (7 − mulligan_count) cards.
    """
    rng = state.rng
    for muls in range(max_mulligans + 1):
        rng.shuffle(state.library)
        candidate = state.library[:7]
        score = hand_quality(candidate, profile, muls)
        if score >= profile.keep_threshold or muls == max_mulligans:
            state.hand = candidate
            state.library = state.library[7:]
            state.mulligans_taken = muls
            # Bottom ``muls`` cards from the kept hand (lowest-quality first).
            if muls > 0:
                ordered = sorted(state.hand, key=lambda c: _bottom_priority(c, profile))
                bottom = ordered[:muls]
                for b in bottom:
                    state.hand.remove(b)
                    state.library.append(b)
            state.log(event="keep_hand", mulligans=muls, score=round(score, 2),
                     hand=[c.name for c in state.hand])
            return
        state.library = state.library + candidate
        state.log(event="mulligan", mulligans=muls + 1, score=round(score, 2))


def _bottom_priority(card: CardInPlay, profile: MulliganProfile) -> tuple[int, int]:
    if card.name in profile.critical_card_names:
        return (10, -int(card.profile.cost_vector.cmc))
    if card.is_land:
        return (3, 0)
    return (1, int(card.profile.cost_vector.cmc) * -1)
