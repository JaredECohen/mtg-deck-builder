"""DeckRationale — the structured explanation payload.

Built from the optimizer result (Phase 5), the simulator metrics
(Phases 2-3), the synergy graph (Phase 4), and the critic transcript
(Phase 7). Returned alongside the deck so the user sees:

* the win plan (per-turn synopsis)
* the soft matchups + sideboard plan
* the mulligan guide (what to keep, what to bin)
* the key turns (Tx-Ty: deploy threat, T(x+1): close)
* the critic transcript (what was flagged, what was fixed)

The LLM (Skill: ``goldfish-coach``) layers prose over these
structured facts. Tests cover the structured path; the LLM prose is
optional and falls back to a deterministic template.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from app.critic.envelope import DeckEnvelope
from app.optimizer.fitness import OptimizerCandidate


logger = logging.getLogger(__name__)


@dataclass
class TurnPlan:
    turn: int
    description: str


@dataclass
class MulliganGuide:
    keep_examples: list[str] = field(default_factory=list)
    mulligan_examples: list[str] = field(default_factory=list)
    keep_threshold_summary: str = ""


@dataclass
class MatchupPlan:
    opponent_archetype: str
    win_rate: float
    plan: str
    sideboard_in: list[str] = field(default_factory=list)
    sideboard_out: list[str] = field(default_factory=list)


@dataclass
class CriticRoundSummary:
    round: int
    flagged: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)


@dataclass
class CoachProse:
    """Optional LLM-narrated prose blocks that decorate the structured
    rationale. Empty/None fields signal the frontend to fall back to
    the structured fields alone."""

    headline_paragraph: str = ""
    win_plan_summary: str = ""
    mulligan_paragraph: str = ""
    matchup_summaries: list[dict[str, str]] = field(default_factory=list)
    weaknesses_paragraph: str = ""
    critic_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline_paragraph": self.headline_paragraph,
            "win_plan_summary": self.win_plan_summary,
            "mulligan_paragraph": self.mulligan_paragraph,
            "matchup_summaries": list(self.matchup_summaries),
            "weaknesses_paragraph": self.weaknesses_paragraph,
            "critic_summary": self.critic_summary,
        }


@dataclass
class DeckRationale:
    """Structured 'why this deck wins' payload returned with each
    optimized deck. Frontend renders sections from these fields."""

    headline: str = ""
    archetype: str = ""
    avg_kill_turn: float = 0.0
    win_rate: float = 0.0
    why_this_wins: list[str] = field(default_factory=list)
    key_turns: list[TurnPlan] = field(default_factory=list)
    mulligan_guide: MulliganGuide = field(default_factory=MulliganGuide)
    soft_matchups: list[MatchupPlan] = field(default_factory=list)
    sideboard_priorities: list[str] = field(default_factory=list)
    critic_transcript: list[CriticRoundSummary] = field(default_factory=list)
    weakness_callouts: list[str] = field(default_factory=list)
    fitness_breakdown: dict[str, float] = field(default_factory=dict)
    cards_breakdown: dict[str, list[str]] = field(default_factory=dict)
    coach_prose: CoachProse | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "headline": self.headline,
            "archetype": self.archetype,
            "avg_kill_turn": self.avg_kill_turn,
            "win_rate": self.win_rate,
            "why_this_wins": list(self.why_this_wins),
            "key_turns": [{"turn": t.turn, "description": t.description} for t in self.key_turns],
            "mulligan_guide": {
                "keep_examples": list(self.mulligan_guide.keep_examples),
                "mulligan_examples": list(self.mulligan_guide.mulligan_examples),
                "keep_threshold_summary": self.mulligan_guide.keep_threshold_summary,
            },
            "soft_matchups": [
                {
                    "opponent_archetype": m.opponent_archetype,
                    "win_rate": m.win_rate,
                    "plan": m.plan,
                    "sideboard_in": list(m.sideboard_in),
                    "sideboard_out": list(m.sideboard_out),
                }
                for m in self.soft_matchups
            ],
            "sideboard_priorities": list(self.sideboard_priorities),
            "critic_transcript": [
                {"round": r.round, "flagged": list(r.flagged), "fixed": list(r.fixed)}
                for r in self.critic_transcript
            ],
            "weakness_callouts": list(self.weakness_callouts),
            "fitness_breakdown": dict(self.fitness_breakdown),
            "cards_breakdown": {k: list(v) for k, v in self.cards_breakdown.items()},
            "coach_prose": self.coach_prose.to_dict() if self.coach_prose else None,
        }


_PROSE_CACHE: dict[str, CoachProse] = {}
_PROSE_CACHE_LOCK = RLock()
_PROSE_CACHE_MAX = 128


def _prose_cache_key(rationale: DeckRationale) -> str:
    payload = json.dumps(rationale.to_dict(), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _invoke_goldfish_coach(rationale: DeckRationale) -> CoachProse | None:
    """Call the ``goldfish-coach`` Skill via the Anthropic SDK to produce
    narrated prose blocks. Returns None if the API key is absent, the
    SDK isn't installed, or the call fails — caller falls back to
    structured-only rationale.

    Cached by structured-rationale hash so repeat optimizer cache hits
    don't re-spend on the LLM.
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        return None
    if os.getenv("MTG_COACH_DISABLE", "").lower() in {"1", "true", "yes"}:
        return None
    cache_key = _prose_cache_key(rationale)
    with _PROSE_CACHE_LOCK:
        cached = _PROSE_CACHE.get(cache_key)
        if cached is not None:
            return cached
    try:
        from pathlib import Path
        from anthropic import Anthropic  # lazy
    except Exception:  # noqa: BLE001
        return None
    skill_path = Path(".claude/skills/goldfish-coach/SKILL.md")
    system_prompt = skill_path.read_text() if skill_path.exists() else ""
    if not system_prompt:
        return None
    try:
        client = Anthropic()
        message = client.messages.create(
            model=os.getenv("MTG_COACH_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=1024,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": json.dumps(rationale.to_dict()),
            }],
        )
        text = message.content[0].text
        payload = json.loads(text)
        prose = CoachProse(
            headline_paragraph=str(payload.get("headline_paragraph", "")),
            win_plan_summary=str(payload.get("win_plan_summary", "")),
            mulligan_paragraph=str(payload.get("mulligan_paragraph", "")),
            matchup_summaries=list(payload.get("matchup_summaries") or []),
            weaknesses_paragraph=str(payload.get("weaknesses_paragraph", "")),
            critic_summary=str(payload.get("critic_summary", "")),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("goldfish-coach invocation failed: %s", exc)
        return None
    with _PROSE_CACHE_LOCK:
        _PROSE_CACHE[cache_key] = prose
        if len(_PROSE_CACHE) > _PROSE_CACHE_MAX:
            # Drop oldest by insertion order (dict preserves it).
            oldest = next(iter(_PROSE_CACHE))
            del _PROSE_CACHE[oldest]
    return prose


def clear_prose_cache() -> None:
    """For tests — reset the global prose cache."""
    with _PROSE_CACHE_LOCK:
        _PROSE_CACHE.clear()


def build_deck_rationale(
    candidate: OptimizerCandidate,
    *,
    final_envelope: DeckEnvelope | None = None,
    critic_rounds: list | None = None,
    invoke_coach: bool = True,
) -> DeckRationale:
    """Compose a DeckRationale from optimizer + critic outputs."""
    fitness = candidate.fitness.to_dict() if candidate.fitness else {}
    archetype = fitness.get("archetype", "midrange")
    avg_kt = fitness.get("avg_kill_turn", 0.0)
    win_rate = fitness.get("win_rate", 0.0)

    rationale = DeckRationale(
        archetype=archetype,
        avg_kill_turn=float(avg_kt) if avg_kt else 0.0,
        win_rate=float(win_rate) if win_rate else 0.0,
        fitness_breakdown={
            k: v for k, v in fitness.items() if isinstance(v, (int, float))
        },
    )

    rationale.headline = _compose_headline(rationale)
    rationale.why_this_wins = _compose_why_wins(candidate, fitness)
    rationale.key_turns = _compose_key_turns(archetype, avg_kt)
    rationale.mulligan_guide = _compose_mulligan_guide(archetype, candidate)
    rationale.weakness_callouts = _compose_weaknesses(fitness)
    rationale.cards_breakdown = _compose_cards_breakdown(candidate)

    if final_envelope is not None and final_envelope.matchup_matrix:
        rationale.soft_matchups = _compose_soft_matchups(final_envelope.matchup_matrix)
    else:
        # Optimizer fitness may carry the matchup matrix in raw — surface it
        # even without a critic envelope so the rationale always has matchup
        # data when matchup simulation was enabled.
        raw_matrix = (candidate.fitness.raw or {}).get("matchup_matrix") if candidate.fitness else None
        if raw_matrix:
            rationale.soft_matchups = _compose_soft_matchups(raw_matrix)

    if critic_rounds:
        rationale.critic_transcript = _compose_critic_transcript(critic_rounds)

    if invoke_coach:
        rationale.coach_prose = _invoke_goldfish_coach(rationale)

    return rationale


def _compose_headline(r: DeckRationale) -> str:
    archetype_label = {
        "aggro": "fast aggressive",
        "combo": "explosive combo",
        "control": "patient control",
        "midrange": "value-oriented midrange",
    }.get(r.archetype, r.archetype)
    if r.avg_kill_turn:
        return f"{archetype_label.title()} deck — goldfishes turn {r.avg_kill_turn:.1f} on average."
    return f"{archetype_label.title()} deck."


def _compose_why_wins(candidate: OptimizerCandidate, fitness: dict) -> list[str]:
    out: list[str] = []
    if fitness.get("kill_turn_score", 0) >= 0.65:
        out.append("Curve and damage density support a fast clock.")
    if fitness.get("mana_consistency", 0) >= 0.85:
        out.append("Mana base hits color requirements consistently on curve.")
    if fitness.get("redundancy", 0) >= 0.7:
        out.append("Redundant role coverage — losing one piece doesn't break the plan.")
    if fitness.get("synergy_density", 0) >= 0.5:
        out.append("Cards reinforce each other through clear enabler-payoff loops.")
    if fitness.get("role_balance", 0) >= 0.7:
        out.append("Balanced role profile: threats, interaction, and value all covered.")
    if not out:
        out.append("Optimizer converged on this configuration as the best in the seed neighborhood.")
    return out


def _compose_key_turns(archetype: str, avg_kt: float | None) -> list[TurnPlan]:
    if archetype == "aggro":
        return [
            TurnPlan(1, "Land + 1-drop threat (Goblin Guide / Monastery Swiftspear) or burn."),
            TurnPlan(2, "Land + 2-drop threat or curve a 1-drop and a burn spell."),
            TurnPlan(3, "Push damage; convert any remaining mana to burn at face."),
            TurnPlan(int(avg_kt or 5), "Close with reach: Skewer, Lightning Bolt, Boros Charm."),
        ]
    if archetype == "combo":
        return [
            TurnPlan(1, "Cantrip; develop mana."),
            TurnPlan(2, "Tutor for missing combo piece OR deploy enabler."),
            TurnPlan(3, "Assemble combo. Hold protection if available."),
            TurnPlan(int(avg_kt or 4), "Resolve combo; close the game."),
        ]
    if archetype == "control":
        return [
            TurnPlan(1, "Land + scry/cantrip; pass with mana up."),
            TurnPlan(2, "Counter or removal at instant speed."),
            TurnPlan(4, "Resolve a wrath or finisher."),
            TurnPlan(int(avg_kt or 8), "Stabilize + deploy closer; protect with held interaction."),
        ]
    return [
        TurnPlan(1, "Land + 1-drop value or removal."),
        TurnPlan(2, "Develop board; trade efficiently."),
        TurnPlan(3, "Deploy 3-drop threat or planeswalker."),
        TurnPlan(4, "Apply pressure; force opponent to interact unfavorably."),
        TurnPlan(int(avg_kt or 6), "Close out with a finisher."),
    ]


def _compose_mulligan_guide(archetype: str, candidate: OptimizerCandidate) -> MulliganGuide:
    if archetype == "aggro":
        return MulliganGuide(
            keep_examples=[
                "2 lands + Goblin Guide + Lightning Bolt + 2-drop threat",
                "3 lands + 2 burn spells + 1-drop threat",
            ],
            mulligan_examples=[
                "0 or 1 land hands",
                "All 3-CMC+ cards (no early plays)",
                "Pure removal hand with no clock",
            ],
            keep_threshold_summary="Keep with 2-4 lands and at least one play before turn 3.",
        )
    if archetype == "combo":
        return MulliganGuide(
            keep_examples=[
                "2-3 lands + tutor + protection",
                "2 lands + cantrip + combo enabler",
            ],
            mulligan_examples=[
                "Hands without a tutor or cantrip",
                "All payoff, no enabler",
            ],
            keep_threshold_summary="Keep if a clear path to combo by turn 4-5 exists.",
        )
    if archetype == "control":
        return MulliganGuide(
            keep_examples=[
                "3-4 lands + counterspell + removal",
                "3 lands + cantrip + 2-mana interaction",
            ],
            mulligan_examples=[
                "Hands without interaction (vulnerable to fast aggro)",
                "Land-light hands with all 4-CMC+ cards",
            ],
            keep_threshold_summary="Keep with 3-5 lands and ≥2 pieces of interaction.",
        )
    return MulliganGuide(
        keep_examples=["2-4 lands with curved-out plays from turns 1-3"],
        mulligan_examples=["No 1- or 2-drop, all 4-CMC top-end"],
        keep_threshold_summary="Keep with reasonable mana + early action.",
    )


def _compose_weaknesses(fitness: dict) -> list[str]:
    out: list[str] = []
    if fitness.get("synergy_density", 1) < 0.4:
        out.append("Card synergy is light — wins through raw card quality, not interactions.")
    if fitness.get("redundancy", 1) < 0.5:
        out.append("Single points of failure exist; expect variance under disruption.")
    if fitness.get("mana_consistency", 1) < 0.85:
        out.append("Mana base under-saturated; some hands will color-screw.")
    if fitness.get("kill_turn_score", 1) < 0.4:
        out.append("Slow clock — vulnerable to faster aggro decks without sideboard answers.")
    return out


def _compose_cards_breakdown(candidate: OptimizerCandidate) -> dict[str, list[str]]:
    buckets = {
        "lands": [],
        "threats": [],
        "removal": [],
        "value_engines": [],
        "combo_pieces": [],
        "other": [],
    }
    seen: set[str] = set()
    for profile, type_line in candidate.deck:
        if profile.name in seen:
            continue
        seen.add(profile.name)
        rw = profile.role_weights
        if rw.land >= 0.9:
            buckets["lands"].append(profile.name)
        elif profile.effect_vector.is_combo_payoff or profile.effect_vector.closes_game:
            buckets["combo_pieces"].append(profile.name)
        elif rw.removal >= 0.4 or profile.effect_vector.is_counterspell:
            buckets["removal"].append(profile.name)
        elif rw.threat >= 0.4 or rw.closer >= 0.3:
            buckets["threats"].append(profile.name)
        elif rw.value_engine >= 0.4:
            buckets["value_engines"].append(profile.name)
        else:
            buckets["other"].append(profile.name)
    return buckets


def _compose_soft_matchups(matrix: dict[str, float]) -> list[MatchupPlan]:
    plans: list[MatchupPlan] = []
    for opponent, winrate in sorted(matrix.items(), key=lambda kv: kv[1]):
        if winrate >= 0.55:
            plan = "Favored — keep the pressure on, sequence threats over interaction."
        elif winrate >= 0.45:
            plan = "Even — match their tempo; sideboard for grindy edge."
        else:
            plan = "Unfavored — sideboard plan must close gap; consider transformative plan."
        plans.append(MatchupPlan(opponent_archetype=opponent, win_rate=winrate, plan=plan))
    return plans


def _compose_critic_transcript(rounds) -> list[CriticRoundSummary]:
    out: list[CriticRoundSummary] = []
    for r in rounds:
        flagged = []
        critique = r.critique if isinstance(r.critique, dict) else getattr(r, "critique", {})
        if isinstance(critique, dict):
            for item in critique.get("items", []):
                flagged.append(item.get("summary", ""))
        out.append(CriticRoundSummary(
            round=r.round if hasattr(r, "round") else 0,
            flagged=[f for f in flagged if f],
            fixed=critique.get("required_fixes", []) if isinstance(critique, dict) else [],
        ))
    return out
