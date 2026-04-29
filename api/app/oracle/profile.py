from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

PROFILE_VERSION = 1

ManaPip = Literal["W", "U", "B", "R", "G", "C", "X", "S"]
TriggerType = Literal[
    "etb",
    "ltb",
    "dies",
    "attacks",
    "blocks",
    "deals_damage",
    "cast_trigger",
    "cast_noncreature",
    "cast_instant_or_sorcery",
    "upkeep",
    "end_step",
    "draw_step",
    "combat_damage",
    "spell_resolves",
    "static",
    "activated",
    "none",
]
ActionKind = Literal[
    "draw",
    "damage",
    "destroy",
    "exile",
    "counter",
    "create_token",
    "add_mana",
    "mill",
    "discard",
    "tutor",
    "gain_life",
    "lose_life",
    "pump",
    "scry",
    "surveil",
    "return_to_hand",
    "tap",
    "untap",
    "sacrifice",
    "copy_spell",
    "win_game",
    "extra_turn",
    "set_life",
    "deal_damage_each",
    "fight",
    "transform",
    "investigate",
    "treasure",
    "food",
    "clue",
    "blood",
    "uncategorized",
]
Role = Literal[
    "closer",
    "threat",
    "enabler",
    "payoff",
    "disruption",
    "removal",
    "fixer",
    "value_engine",
    "tutor",
    "protection",
    "land",
]
InteractionWindow = Literal["instant", "sorcery", "static", "permanent", "activated", "triggered"]


@dataclass
class CostVector:
    generic: int = 0
    pips: dict[str, int] = field(default_factory=dict)
    alt_costs: list[str] = field(default_factory=list)
    additional_costs: list[str] = field(default_factory=list)
    cmc: float = 0.0
    pip_intensity: float = 0.0
    color_demand: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Action:
    kind: ActionKind
    quantity: float = 0.0
    target: str | None = None
    text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Effect:
    trigger: TriggerType = "none"
    cost: str | None = None
    actions: list[Action] = field(default_factory=list)
    text: str = ""
    conditional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "cost": self.cost,
            "actions": [a.to_dict() for a in self.actions],
            "text": self.text,
            "conditional": self.conditional,
        }


@dataclass
class EffectVector:
    ca_delta: float = 0.0
    tempo_delta: float = 0.0
    board_impact: float = 0.0
    removal_scope: list[str] = field(default_factory=list)
    damage_dealt: float = 0.0
    life_gained: float = 0.0
    life_lost: float = 0.0
    cards_drawn: float = 0.0
    cards_milled: float = 0.0
    creatures_made: float = 0.0
    mana_produced: float = 0.0
    interaction_window: InteractionWindow = "permanent"
    speed_score: float = 0.0
    targets_creatures: bool = False
    targets_permanents: bool = False
    targets_players: bool = False
    targets_graveyard: bool = False
    is_counterspell: bool = False
    is_tutor: bool = False
    is_combo_payoff: bool = False
    closes_game: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RoleWeights:
    closer: float = 0.0
    threat: float = 0.0
    enabler: float = 0.0
    payoff: float = 0.0
    disruption: float = 0.0
    removal: float = 0.0
    fixer: float = 0.0
    value_engine: float = 0.0
    tutor: float = 0.0
    protection: float = 0.0
    land: float = 0.0

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    def normalize(self) -> "RoleWeights":
        total = sum(self.to_dict().values())
        if total <= 0:
            return self
        scaled = {k: v / total for k, v in self.to_dict().items()}
        return RoleWeights(**scaled)


@dataclass
class ComboPrimitives:
    triggers: list[str] = field(default_factory=list)
    produces: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return asdict(self)


@dataclass
class CardProfile:
    card_id: str
    name: str
    cost_vector: CostVector
    effect_vector: EffectVector
    role_weights: RoleWeights
    combo_primitives: ComboPrimitives
    oracle_ast: list[Effect] = field(default_factory=list)
    profile_version: int = PROFILE_VERSION
    parse_method: Literal["pattern", "skill", "fallback"] = "pattern"
    parse_coverage: float = 0.0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "card_id": self.card_id,
            "name": self.name,
            "cost_vector": self.cost_vector.to_dict(),
            "effect_vector": self.effect_vector.to_dict(),
            "role_weights": self.role_weights.to_dict(),
            "combo_primitives": self.combo_primitives.to_dict(),
            "oracle_ast": [e.to_dict() for e in self.oracle_ast],
            "profile_version": self.profile_version,
            "parse_method": self.parse_method,
            "parse_coverage": self.parse_coverage,
            "notes": list(self.notes),
        }
