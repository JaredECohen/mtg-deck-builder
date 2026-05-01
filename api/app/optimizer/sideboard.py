"""Sideboard generator.

Inputs: candidate mainboard, available card pool, matchup matrix.
Output: a 15-card sideboard with each slot tagged by the matchup it
answers.

Algorithm:

1. Sort opponents by win rate, weakest first.
2. For each weak matchup, classify the opponent's archetype (aggro,
   combo, control, midrange) using role-profile aggregation.
3. Look up the corresponding *answer category* (e.g. aggro → lifegain
   + sweepers; combo → discard + counters; graveyard → exile).
4. Score pool cards by how well they match the answer category.
5. Allocate slots proportional to matchup weakness, capped at the
   sideboard size.

The output is *suggestions* — a real player will tune from here, but
the structured plan is what makes the deck shippable as a tournament
list.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.optimizer.swap_proposals import BASIC_NAMES
from app.oracle.profile import CardProfile
from app.sim.policy import select_policy


# Map archetype labels (used by the matchup matrix) to *answer
# categories* — what kind of card hates this archetype out.
ANSWER_CATEGORIES: dict[str, list[str]] = {
    "aggro": ["lifegain", "sweeper", "early_blocker"],
    "burn": ["lifegain", "early_blocker", "protection"],
    "combo": ["counter", "discard", "graveyard_hate", "tempo_disruption"],
    "control": ["threat", "uncounterable", "planeswalker"],
    "midrange": ["threat", "card_advantage", "removal"],
    "graveyard": ["graveyard_hate", "exile_removal"],
    "ramp": ["land_destruction", "counter", "fast_clock"],
}


@dataclass
class SideboardSlot:
    card: CardProfile
    type_line: str
    matchup_target: str
    answer_category: str
    rationale: str


@dataclass
class SideboardPlan:
    slots: list[SideboardSlot] = field(default_factory=list)
    matchup_coverage: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def total_cards(self) -> int:
        return len(self.slots)

    def to_dict(self) -> dict[str, Any]:
        return {
            "slots": [
                {
                    "card_name": s.card.name,
                    "type_line": s.type_line,
                    "matchup_target": s.matchup_target,
                    "answer_category": s.answer_category,
                    "rationale": s.rationale,
                }
                for s in self.slots
            ],
            "matchup_coverage": dict(self.matchup_coverage),
            "total_cards": self.total_cards,
            "notes": list(self.notes),
        }


def build_sideboard(
    candidate_deck: list[tuple[CardProfile, str]],
    pool: list[tuple[CardProfile, str]],
    matchup_matrix: dict[str, float],
    *,
    sideboard_size: int = 15,
    losing_threshold: float = 0.50,
    matchup_archetypes: dict[str, str] | None = None,
    deck_colors: list[str] | None = None,
) -> SideboardPlan:
    """Construct a sideboard plan.

    ``matchup_archetypes`` maps opponent labels to archetype names
    used by :data:`ANSWER_CATEGORIES`. When None, the sideboard infers
    archetype labels from the matchup label itself (a "Burn" opponent
    looks up the "burn" answer category, a "Tron" opponent the "ramp"
    category).

    ``deck_colors`` constrains sideboard candidates to the deck's
    color identity — a mono-R deck shouldn't pull a Counterspell from
    a UR pool. When None, the function infers the colors from the
    candidate deck's mainboard.

    ``sideboard_size=0`` (Commander) returns an empty plan.
    """
    plan = SideboardPlan()
    if sideboard_size <= 0:
        plan.notes.append("format does not use a sideboard")
        return plan
    if not matchup_matrix:
        plan.notes.append("no matchup matrix available — empty sideboard")
        return plan
    if deck_colors is None:
        deck_colors = sorted({
            color
            for prof, _ in candidate_deck
            for color in prof.cost_vector.color_demand.keys()
        })
    deck_color_set = set(deck_colors)

    # Sort opponents by ascending win rate (weakest first).
    sorted_matchups = sorted(matchup_matrix.items(), key=lambda kv: kv[1])
    losing = [(label, wr) for label, wr in sorted_matchups if wr < losing_threshold]

    # If everything is winning, still spend a few slots on flex answers
    # for the closest matchups.
    if not losing:
        losing = sorted_matchups[: min(3, len(sorted_matchups))]

    # Allocate slots proportional to how losing each matchup is.
    weights = []
    for label, wr in losing:
        weakness = max(0.05, losing_threshold - wr)  # 0..0.5
        weights.append((label, weakness))
    weight_sum = sum(w for _, w in weights) or 1.0

    deck_names = {p.name for p, _ in candidate_deck}

    for label, weight in weights:
        slot_target = int(round(sideboard_size * (weight / weight_sum)))
        slot_target = max(1, slot_target)
        archetype = (matchup_archetypes or {}).get(label) or _infer_archetype_label(label)
        categories = ANSWER_CATEGORIES.get(archetype, ANSWER_CATEGORIES["midrange"])

        added = 0
        for category in categories:
            if added >= slot_target:
                break
            for prof, type_line in _rank_pool_for_category(
                pool, category, deck_names, plan, deck_color_set
            ):
                if added >= slot_target:
                    break
                if len(plan.slots) >= sideboard_size:
                    break
                plan.slots.append(SideboardSlot(
                    card=prof,
                    type_line=type_line,
                    matchup_target=label,
                    answer_category=category,
                    rationale=f"Improves vs {label} ({category}).",
                ))
                added += 1
        plan.matchup_coverage[label] = added
        if len(plan.slots) >= sideboard_size:
            break

    # Pad with flex slots (uncategorized) if we're under budget.
    while len(plan.slots) < sideboard_size and pool:
        flex = _pick_flex_card(pool, deck_names, plan, deck_color_set)
        if flex is None:
            break
        plan.slots.append(SideboardSlot(
            card=flex[0],
            type_line=flex[1],
            matchup_target="flex",
            answer_category="flex",
            rationale="Flex slot — keep for general tuning.",
        ))

    return plan


def _infer_archetype_label(matchup_label: str) -> str:
    """Heuristic: figure out the opponent's broad archetype from its
    matchup label. Strings come from META_DECKS keys."""
    lower = matchup_label.lower()
    if "burn" in lower:
        return "burn"
    if "tron" in lower or "ramp" in lower or "amulet" in lower:
        return "ramp"
    if "living end" in lower or "graveyard" in lower or "dredge" in lower or "scapeshift" in lower:
        return "graveyard"
    if "control" in lower or "azorius" in lower:
        return "control"
    if "tempo" in lower or "murktide" in lower:
        return "midrange"
    if "aggro" in lower or "hammer" in lower:
        return "aggro"
    if "combo" in lower or "twin" in lower or "storm" in lower:
        return "combo"
    return "midrange"


def _rank_pool_for_category(
    pool: list[tuple[CardProfile, str]],
    category: str,
    deck_names: set[str],
    plan: SideboardPlan,
    deck_colors: set[str] | None = None,
) -> list[tuple[CardProfile, str]]:
    """Return pool cards ranked by their fit for the given category.

    Deduped by card name. ``deck_colors`` filters out cards whose
    colored mana cost requires colors the deck can't reliably produce
    — keeps a mono-R sideboard from picking Counterspell.
    """
    already_in_sideboard = {s.card.name for s in plan.slots}
    seen_names: set[str] = set()
    candidates: list[tuple[float, tuple[CardProfile, str]]] = []
    for prof, type_line in pool:
        if prof.name in BASIC_NAMES:
            continue
        if prof.name in already_in_sideboard:
            continue
        if prof.name in seen_names:
            continue
        if deck_colors is not None and deck_colors:
            offcolor = set(prof.cost_vector.color_demand.keys()) - deck_colors
            if offcolor:
                continue
        score = _category_score(prof, category)
        if score <= 0:
            continue
        if prof.name in deck_names:
            score += 0.1
        seen_names.add(prof.name)
        candidates.append((score, (prof, type_line)))
    candidates.sort(key=lambda kv: -kv[0])
    return [pa for _, pa in candidates[:8]]


def _category_score(profile: CardProfile, category: str) -> float:
    """Heuristic match score between a card and an answer category."""
    rw = profile.role_weights
    ev = profile.effect_vector
    text = " ".join((profile.combo_primitives.keywords or []))

    if category == "lifegain":
        if ev.life_gained >= 1:
            return 1.0 + ev.life_gained * 0.3
        if "lifelink" in text.lower():
            return 0.7
        return 0.0
    if category == "sweeper":
        # Removal that hits multiple creatures.
        if "creature" in (ev.removal_scope or []) and (ev.board_impact or 0) >= 3:
            return 1.0
        return 0.0
    if category == "early_blocker":
        if profile.cost_vector.cmc <= 2 and rw.threat > 0:
            return 0.7
        return 0.0
    if category == "protection":
        if rw.protection > 0:
            return 1.0
        return 0.0
    if category == "counter":
        if ev.is_counterspell:
            return 1.2
        if rw.disruption >= 0.4 and profile.cost_vector.cmc <= 3:
            return 0.6
        return 0.0
    if category == "discard":
        # Cards whose effect text drops opponents' cards from hand.
        if any(a.kind == "discard" for eff in profile.oracle_ast for a in eff.actions):
            return 1.0
        return 0.0
    if category == "graveyard_hate":
        text_lower = " ".join(eff.text.lower() for eff in profile.oracle_ast)
        if "graveyard" in text_lower and ("exile" in text_lower or "remove" in text_lower):
            return 1.0
        if "exile" in (ev.removal_scope or []):
            return 0.5
        return 0.0
    if category == "exile_removal":
        if "exile" in (ev.removal_scope or []):
            return 1.0
        return 0.0
    if category == "tempo_disruption":
        if rw.disruption >= 0.4 or ev.is_counterspell:
            return 0.7
        return 0.0
    if category == "threat":
        if rw.threat >= 0.5 and profile.cost_vector.cmc <= 4:
            return 1.0
        return 0.0
    if category == "uncounterable":
        # Heuristic — cards with cascade or alternate-cast aren't
        # counterable; otherwise look for "can't be countered" text.
        text_lower = " ".join(eff.text.lower() for eff in profile.oracle_ast)
        if "can't be countered" in text_lower or "cascade" in text_lower:
            return 1.0
        return 0.0
    if category == "planeswalker":
        if profile.role_weights.value_engine >= 0.3 and "planeswalker" in (text.lower()):
            return 1.0
        return 0.0
    if category == "card_advantage":
        if ev.cards_drawn >= 1:
            return min(1.0, ev.cards_drawn * 0.5)
        return 0.0
    if category == "removal":
        if rw.removal >= 0.4:
            return 1.0
        return 0.0
    if category == "land_destruction":
        text_lower = " ".join(eff.text.lower() for eff in profile.oracle_ast)
        if "destroy target" in text_lower and "land" in text_lower:
            return 1.0
        return 0.0
    if category == "fast_clock":
        if rw.threat >= 0.5 and profile.cost_vector.cmc <= 2:
            return 1.0
        return 0.0
    return 0.0


def _pick_flex_card(
    pool: list[tuple[CardProfile, str]],
    deck_names: set[str],
    plan: SideboardPlan,
    deck_colors: set[str] | None = None,
) -> tuple[CardProfile, str] | None:
    already_sb = {s.card.name for s in plan.slots}
    for prof, type_line in pool:
        if prof.name in BASIC_NAMES:
            continue
        if prof.name in already_sb:
            continue
        if prof.name in deck_names:
            continue
        if deck_colors is not None and deck_colors:
            offcolor = set(prof.cost_vector.color_demand.keys()) - deck_colors
            if offcolor:
                continue
        if prof.role_weights.removal >= 0.3 or prof.effect_vector.is_counterspell:
            return (prof, type_line)
    return None
