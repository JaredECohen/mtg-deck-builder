"""The critic rubric.

Six evidence-bound checks. The critic *cannot* fail a deck on grounds
outside the rubric — it must cite a rubric_id and supply matching
evidence. We also run the rubric server-side as a *deterministic
sanity check* so a malformed critique can be rejected before the
loop even consults the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.critic.envelope import CritiqueItem, DeckEnvelope


@dataclass
class RubricCheck:
    id: str
    title: str
    description: str
    threshold_hint: str = ""


RUBRIC: list[RubricCheck] = [
    RubricCheck(
        id="R1_win_condition",
        title="Win condition coherence",
        description="Deck must show a closer and the simulator must show it actually closes by an appropriate turn for the format.",
        threshold_hint="kill_turn ≤ 7 for aggro/combo Modern; ≤ 12 for control",
    ),
    RubricCheck(
        id="R2_mana_consistency",
        title="Mana consistency",
        description="Mana-base solver shows ≥ 85% on-curve color hits by the relevant turns.",
        threshold_hint="mana_consistency ≥ 0.85",
    ),
    RubricCheck(
        id="R3_meta_interaction",
        title="Interaction density vs. meta",
        description="Matchup matrix must show no losing matchup against any top-3 meta deck without a sideboard answer.",
        threshold_hint="all matchup_winrates ≥ 0.40 OR sideboard contains an answer card",
    ),
    RubricCheck(
        id="R4_synergy_redundancy",
        title="Synergy clique redundancy",
        description="Critical synergy edges should not bottleneck on a single tutor or single payoff.",
        threshold_hint="≥ 2 redundant copies of every critical card",
    ),
    RubricCheck(
        id="R5_constraints",
        title="Constraint adherence",
        description="The optimized deck must respect every user constraint (budget, color, includes, excludes).",
        threshold_hint="zero constraint violations",
    ),
    RubricCheck(
        id="R6_dead_cards",
        title="Dead card audit",
        description="No card should be unplayed in > 5% of simulated games.",
        threshold_hint="every slot is exercised in ≥ 95% of goldfish runs",
    ),
]
RUBRIC_BY_ID = {c.id: c for c in RUBRIC}


def run_rubric(envelope: DeckEnvelope) -> list[CritiqueItem]:
    """Deterministic, simulator-grounded rubric pass.

    Used for two purposes:
    1. *Pre-filter* — if the deterministic rubric is already clean,
       short-circuit to APPROVE without consulting the critic LLM.
    2. *Sanity gate* — every LLM critique item is checked against the
       deterministic finding. The LLM cannot APPROVE a deck the
       deterministic pass flags as failing.
    """
    items: list[CritiqueItem] = []
    metrics = envelope.simulator_metrics or {}
    fitness = envelope.fitness or {}

    # R1 — win condition
    avg_kt = metrics.get("avg_kill_turn")
    archetype = fitness.get("archetype", "midrange")
    target = 7 if archetype in ("aggro", "combo") else 12
    if avg_kt is not None and avg_kt > target:
        items.append(CritiqueItem(
            rubric_id="R1_win_condition",
            severity="error",
            summary=f"avg kill turn {avg_kt:.1f} exceeds {target} for {archetype}",
            evidence={"avg_kill_turn": avg_kt, "archetype": archetype, "target": target},
            proposed_fix="Lower the curve or add explicit closers/burn.",
        ))

    # R2 — mana consistency
    mc = fitness.get("mana_consistency", 0.0)
    if mc < 0.85:
        items.append(CritiqueItem(
            rubric_id="R2_mana_consistency",
            severity="error" if mc < 0.7 else "warning",
            summary=f"mana consistency {mc:.0%} below 85%",
            evidence={"mana_consistency": mc},
            proposed_fix="Add fixing (more on-color sources or fetchlands).",
        ))

    # R3 — matchup matrix
    matchups = envelope.matchup_matrix or {}
    if matchups:
        weakest = min(matchups.values())
        if weakest < 0.40:
            worst_matchup = min(matchups, key=matchups.get)
            items.append(CritiqueItem(
                rubric_id="R3_meta_interaction",
                severity="warning",
                summary=f"losing matchup vs. {worst_matchup} (winrate {weakest:.0%})",
                evidence={"opponent": worst_matchup, "winrate": weakest},
                proposed_fix="Add a sideboard answer for this matchup.",
            ))

    # R4 — synergy redundancy
    synergy = envelope.synergy_clique or []
    if synergy:
        # Reject only if a critical clique member appears as a 1-of in the deck.
        deck_counts: dict[str, int] = {}
        for entry in envelope.deck:
            name = entry.get("name") if isinstance(entry, dict) else getattr(entry, "name", None)
            if name:
                deck_counts[name] = deck_counts.get(name, 0) + 1
        bottlenecks = [c for c in synergy if deck_counts.get(c, 0) < 2]
        if bottlenecks:
            items.append(CritiqueItem(
                rubric_id="R4_synergy_redundancy",
                severity="warning",
                summary=f"single point of failure: {bottlenecks}",
                evidence={"bottlenecks": bottlenecks, "deck_counts": {c: deck_counts.get(c, 0) for c in synergy}},
                proposed_fix="Run ≥2 copies of each clique member, or add a tutor.",
            ))

    # R5 — constraints
    violations = envelope.constraints.get("violations") if envelope.constraints else None
    if violations:
        items.append(CritiqueItem(
            rubric_id="R5_constraints",
            severity="error",
            summary=f"constraint violations: {violations}",
            evidence={"violations": violations},
            proposed_fix="Reject this candidate; restart annealing within constraint envelope.",
        ))

    # R6 — dead cards
    dead = metrics.get("dead_cards") or []
    if dead:
        items.append(CritiqueItem(
            rubric_id="R6_dead_cards",
            severity="info",
            summary=f"cards rarely cast: {dead[:5]}",
            evidence={"dead_cards": dead},
            proposed_fix="Replace with a card that activates more often.",
        ))

    return items
