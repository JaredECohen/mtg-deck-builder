"""Builder ⇄ Critic JSON envelope schema.

The envelope is the only data the two models exchange. Free-form
prose is forbidden — both sides must conform to the schema. This is
what keeps the loop converging instead of devolving into vibes.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Literal

EnvelopeVersion = "v1"


class Verdict(str, Enum):
    APPROVE = "approve"
    REVISE = "revise"
    REJECT = "reject"


@dataclass
class CritiqueItem:
    """One rubric-bound critique. ``rubric_id`` ties the critique to a
    line in the canonical rubric — without it the item is rejected."""

    rubric_id: str
    severity: Literal["info", "warning", "error"]
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)
    proposed_fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Critique:
    verdict: Verdict
    items: list[CritiqueItem] = field(default_factory=list)
    required_fixes: list[str] = field(default_factory=list)
    optional_fixes: list[str] = field(default_factory=list)
    notes: str = ""

    def is_approved(self) -> bool:
        return self.verdict == Verdict.APPROVE

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "items": [i.to_dict() for i in self.items],
            "required_fixes": list(self.required_fixes),
            "optional_fixes": list(self.optional_fixes),
            "notes": self.notes,
        }


@dataclass
class DeckEnvelope:
    """The deck + evidence package the Builder hands the Critic."""

    version: str = EnvelopeVersion
    deck: list[dict[str, Any]] = field(default_factory=list)
    simulator_metrics: dict[str, Any] = field(default_factory=dict)
    fitness: dict[str, float] = field(default_factory=dict)
    synergy_clique: list[str] = field(default_factory=list)
    matchup_matrix: dict[str, float] = field(default_factory=dict)
    constraints: dict[str, Any] = field(default_factory=dict)
    builder_notes: list[str] = field(default_factory=list)
    round: int = 0
    previous_critique: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "round": self.round,
            "deck": list(self.deck),
            "simulator_metrics": dict(self.simulator_metrics),
            "fitness": dict(self.fitness),
            "synergy_clique": list(self.synergy_clique),
            "matchup_matrix": dict(self.matchup_matrix),
            "constraints": dict(self.constraints),
            "builder_notes": list(self.builder_notes),
            "previous_critique": self.previous_critique,
        }
