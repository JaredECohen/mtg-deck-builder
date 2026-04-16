from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


FormatName = Literal["standard", "modern", "legacy", "commander"]
ModeName = Literal["fast-competitive", "constraint-aware", "creative-but-viable"]
ExperienceLevel = Literal["beginner", "expert"]


class CardRef(BaseModel):
    name: str
    quantity: int = Field(ge=1, le=100)


class ArchetypePackage(BaseModel):
    name: str
    inclusion_rate: float | None = None
    average_quantity: float | None = None
    tags: list[str] = Field(default_factory=list)


class ArchetypeMetadata(BaseModel):
    signature_sample: str | None = None
    source_event_names: list[str] = Field(default_factory=list)
    sample_deck_ids: list[str] = Field(default_factory=list)
    core_cards: list[ArchetypePackage] = Field(default_factory=list)
    flex_cards: list[ArchetypePackage] = Field(default_factory=list)
    sideboard_packages: list[ArchetypePackage] = Field(default_factory=list)
    top_weighted_decks: list[dict[str, str | float]] = Field(default_factory=list)
    similarity_threshold: float | None = None


class CardRecord(BaseModel):
    oracle_id: str | None = None
    name: str
    mana_cost: str = ""
    mana_value: float = 0
    colors: list[str] = Field(default_factory=list)
    color_identity: list[str] = Field(default_factory=list)
    type_line: str
    oracle_text: str = ""
    set_code: str | None = None
    released_at: str | None = None
    image_uri: str | None = None
    legalities: dict[str, str] = Field(default_factory=dict)
    price_usd: float | None = None
    tags: list[str] = Field(default_factory=list)


class CardDetailResponse(BaseModel):
    card: CardRecord


class ArchetypeRecord(BaseModel):
    id: str
    name: str
    format: FormatName
    colors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    strategy: str
    mainboard: list[CardRef]
    sideboard: list[CardRef] = Field(default_factory=list)
    commander: str | None = None
    source_count: int = 0
    avg_placement: float | None = None
    metadata: ArchetypeMetadata = Field(default_factory=ArchetypeMetadata)


class GenerateDeckRequest(BaseModel):
    format: FormatName
    colors: list[str] = Field(default_factory=list)
    playstyle_tags: list[str] = Field(default_factory=list)
    theme_tags: list[str] = Field(default_factory=list)
    budget: float | None = Field(default=None, ge=0)
    include_cards: list[str] = Field(default_factory=list)
    exclude_cards: list[str] = Field(default_factory=list)
    mode: ModeName = "constraint-aware"
    experience_level: ExperienceLevel = "beginner"
    prompt: str = ""


class RefineDeckRequest(BaseModel):
    deck: "DeckResponse"
    refinement_prompt: str


class ValidateDeckRequest(BaseModel):
    format: FormatName
    mainboard: list[CardRef]
    sideboard: list[CardRef] = Field(default_factory=list)
    commander: str | None = None


class ExportDeckRequest(BaseModel):
    deck: "DeckResponse"
    target: Literal["arena", "plain", "csv", "moxfield"] = "plain"


class ScoreBreakdown(BaseModel):
    legality: int
    mana: int
    synergy: int
    prompt_fit: int
    competitiveness: int
    budget_fit: int
    total: int


class ValidationResult(BaseModel):
    is_legal: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    score: ScoreBreakdown


class DeckCardExplanation(BaseModel):
    name: str
    role: str
    reason: str


class DeckResponse(BaseModel):
    format: FormatName
    title: str
    colors: list[str]
    strategy_summary: str
    commander: str | None = None
    mainboard: list[CardRef]
    sideboard: list[CardRef] = Field(default_factory=list)
    estimated_price_usd: float | None = None
    is_legal: bool = True
    validation_errors: list[str] = Field(default_factory=list)
    score: ScoreBreakdown
    explanation: list[str]
    card_notes: list[DeckCardExplanation]
    warnings: list[str] = Field(default_factory=list)
    source_archetypes: list[str] = Field(default_factory=list)
    selected_archetype: ArchetypeRecord | None = None

    @model_validator(mode="after")
    def check_deck_sizes(self) -> "DeckResponse":
        if self.format == "commander" and sum(card.quantity for card in self.mainboard) != 99:
            raise ValueError("Commander decks must include 99 cards in the mainboard.")
        if self.format != "commander" and sum(card.quantity for card in self.mainboard) != 60:
            raise ValueError("Constructed decks must include 60 cards in the mainboard.")
        return self


class MetaSummaryResponse(BaseModel):
    format: FormatName
    archetypes: list[ArchetypeRecord]


RefineDeckRequest.model_rebuild()
ExportDeckRequest.model_rebuild()
