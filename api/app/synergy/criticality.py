"""Criticality scoring: how much does removing a card hurt the deck?

Criticality is the simulator's voice: pull a card out, fill the slot
with a vanilla replacement of the same CMC, re-run the goldfish, and
measure the kill-turn delta. Cards whose removal slows the deck by
≥1 turn are *critical* — the optimizer must not swap them away.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.oracle.profile import CardProfile, ComboPrimitives, CostVector, EffectVector, RoleWeights
from app.sim.goldfish import GoldfishConfig, goldfish
from app.sim.policy._common import Decision
from app.sim.state import GameState


def _vanilla_replacement(profile: CardProfile, type_line: str) -> CardProfile:
    """Construct a 'vanilla' card profile of the same CMC.

    Used as the placeholder when measuring criticality — we can't just
    drop the slot because that would shrink the deck, so we replace
    with a generic card of equivalent cost. For lands, the replacement
    is a basic of a produced color.
    """
    cv = CostVector(
        cmc=profile.cost_vector.cmc,
        pips=dict(profile.cost_vector.pips),
        color_demand=dict(profile.cost_vector.color_demand),
    )
    is_land = "land" in type_line.lower()
    is_creature = "creature" in type_line.lower()
    if is_creature:
        ev = EffectVector(
            board_impact=max(1.0, profile.cost_vector.cmc * 1.0),
            interaction_window="permanent",
        )
        rw = RoleWeights(threat=1.0)
    elif is_land:
        ev = EffectVector(interaction_window="static")
        rw = RoleWeights(land=1.0)
    else:
        ev = EffectVector(interaction_window="sorcery")
        rw = RoleWeights(value_engine=1.0)
    return CardProfile(
        card_id=f"vanilla::{profile.cost_vector.cmc:.0f}",
        name=f"<vanilla-{int(profile.cost_vector.cmc)}>",
        cost_vector=cv,
        effect_vector=ev,
        role_weights=rw,
        combo_primitives=ComboPrimitives(),
        oracle_ast=[],
        profile_version=profile.profile_version,
        parse_method="pattern",
    )


@dataclass
class CriticalityScore:
    card_name: str
    delta_kill_turn: float
    delta_win_rate: float
    is_critical: bool

    def to_dict(self) -> dict:
        return {
            "card_name": self.card_name,
            "delta_kill_turn": self.delta_kill_turn,
            "delta_win_rate": self.delta_win_rate,
            "is_critical": self.is_critical,
        }


def compute_criticality(
    deck: list[tuple[CardProfile, str]],
    *,
    policy: Callable[[GameState], list[Decision]],
    config: GoldfishConfig | None = None,
    candidate_cards: list[str] | None = None,
    threshold: float = 0.75,
) -> list[CriticalityScore]:
    """Score each unique card by simulator-derived removal impact.

    ``candidate_cards`` lets the caller restrict scoring (criticality is
    expensive — N goldfish runs × games-per-run). Only the named cards
    will be scored; if None, every unique card is scored.
    Threshold ``0.75`` means "removing this card slows kill by 0.75
    turns" → considered critical.
    """
    cfg = config or GoldfishConfig(games=200, max_turns=10)

    base_report = goldfish(deck, policy=policy, config=cfg)
    base_kt = base_report.avg_kill_turn
    base_wr = base_report.wins / max(1, base_report.games_played)

    by_name: dict[str, list[int]] = {}
    for i, (profile, _) in enumerate(deck):
        by_name.setdefault(profile.name, []).append(i)

    scores: list[CriticalityScore] = []
    targets = candidate_cards or sorted(by_name)
    for name in targets:
        idxs = by_name.get(name, [])
        if not idxs:
            continue
        i = idxs[0]
        profile, type_line = deck[i]
        # Skip vanilla-replacement of lands and basics — they have no
        # interesting criticality and noise dominates the signal.
        if "land" in type_line.lower():
            continue
        replacement = _vanilla_replacement(profile, type_line)
        modified = list(deck)
        modified[i] = (replacement, type_line)
        rpt = goldfish(modified, policy=policy, config=cfg)
        delta_kt = rpt.avg_kill_turn - base_kt
        delta_wr = (rpt.wins / max(1, rpt.games_played)) - base_wr
        scores.append(
            CriticalityScore(
                card_name=name,
                delta_kill_turn=delta_kt,
                delta_win_rate=delta_wr,
                is_critical=delta_kt >= threshold or delta_wr <= -0.10,
            )
        )

    scores.sort(key=lambda s: -s.delta_kill_turn)
    return scores


def score_card_criticality(
    name: str,
    deck: list[tuple[CardProfile, str]],
    *,
    policy: Callable[[GameState], list[Decision]],
    config: GoldfishConfig | None = None,
) -> CriticalityScore | None:
    """Convenience: score a single card's criticality."""
    results = compute_criticality(
        deck, policy=policy, config=config, candidate_cards=[name]
    )
    return results[0] if results else None
