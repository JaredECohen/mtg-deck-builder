from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


FormatName = Literal["standard", "modern", "pioneer", "legacy", "commander"]
ModeName = Literal["fast-competitive", "constraint-aware", "creative-but-viable"]
ExperienceLevel = Literal["beginner", "expert"]


class CardRef(BaseModel):
    name: str
    quantity: int = Field(ge=1, le=100)


class TournamentDeckIngestMetadata(BaseModel):
    raw_source: str = "unknown"
    ingested_from: str = ""
    source_url: str | None = None
    format_season: str | None = None
    event_tier: str | None = None
    event_size: int | None = None
    finish_label: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    # Canonical display name of the source archetype (when known, e.g. from
    # synthesize_tournament_corpus.py). Used by build_archetypes.py to label
    # the cluster instead of auto-generating "B Graveyard Ramp"-style names.
    archetype_label: str | None = None


class NormalizedTournamentDeckRecord(BaseModel):
    id: str
    source: str
    dedupe_key: str
    source_url: str | None = None
    event_name: str
    event_date: str | None = None
    format: FormatName
    format_season: str | None = None
    event_tier: str | None = None
    event_size: int | None = None
    finish_label: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    player_name: str | None = None
    placement: int | None = None
    wins: int | None = None
    losses: int | None = None
    draws: int | None = None
    colors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    commander: str | None = None
    mainboard: list[CardRef]
    sideboard: list[CardRef] = Field(default_factory=list)
    metadata: TournamentDeckIngestMetadata = Field(default_factory=TournamentDeckIngestMetadata)


class ArchetypePackage(BaseModel):
    name: str
    inclusion_rate: float | None = None
    average_quantity: float | None = None
    tags: list[str] = Field(default_factory=list)


class WeightedCardProfile(BaseModel):
    name: str
    weight: float
    average_quantity: float | None = None
    role: str | None = None


class RoleProfilePoint(BaseModel):
    role: str
    weight: float


class CommanderPackageSummary(BaseModel):
    commander_name: str
    popularity: float = 0
    support_depth: int = 0
    average_lands: float | None = None
    average_ramp: float | None = None
    average_draw: float | None = None
    average_interaction: float | None = None
    signature_cards: list[ArchetypePackage] = Field(default_factory=list)
    synergy_packages: list[ArchetypePackage] = Field(default_factory=list)
    ramp_package: list[ArchetypePackage] = Field(default_factory=list)
    draw_package: list[ArchetypePackage] = Field(default_factory=list)
    interaction_package: list[ArchetypePackage] = Field(default_factory=list)
    land_package: list[ArchetypePackage] = Field(default_factory=list)


class ArchetypeMetadata(BaseModel):
    signature_sample: str | None = None
    source_event_names: list[str] = Field(default_factory=list)
    sample_deck_ids: list[str] = Field(default_factory=list)
    core_cards: list[ArchetypePackage] = Field(default_factory=list)
    flex_cards: list[ArchetypePackage] = Field(default_factory=list)
    land_packages: list[ArchetypePackage] = Field(default_factory=list)
    sideboard_packages: list[ArchetypePackage] = Field(default_factory=list)
    matchup_tech_packages: list[ArchetypePackage] = Field(default_factory=list)
    top_weighted_decks: list[dict[str, str | float]] = Field(default_factory=list)
    similarity_threshold: float | None = None
    archetype_type: Literal["constructed", "commander"] = "constructed"
    color_profile: list[str] = Field(default_factory=list)
    tag_vector: list[WeightedCardProfile] = Field(default_factory=list)
    signature_cards: list[WeightedCardProfile] = Field(default_factory=list)
    normalized_card_vector: list[WeightedCardProfile] = Field(default_factory=list)
    mana_curve_profile: list[dict[str, int | float]] = Field(default_factory=list)
    role_profile: list[RoleProfilePoint] = Field(default_factory=list)
    commander_package: CommanderPackageSummary | None = None


class CardFaceRecord(BaseModel):
    name: str | None = None
    mana_cost: str = ""
    type_line: str = ""
    oracle_text: str = ""
    image_uri: str | None = None


class CardPurchaseLinks(BaseModel):
    scryfall: str | None = None
    tcgplayer: str | None = None
    cardmarket: str | None = None
    amazon_search: str | None = None


class CardRecord(BaseModel):
    oracle_id: str | None = None
    scryfall_id: str | None = None
    name: str
    normalized_name: str | None = None
    mana_cost: str = ""
    mana_value: float = 0
    colors: list[str] = Field(default_factory=list)
    color_identity: list[str] = Field(default_factory=list)
    type_line: str
    oracle_text: str = ""
    keywords: list[str] = Field(default_factory=list)
    layout: str | None = None
    rarity: str | None = None
    set_code: str | None = None
    set_type: str | None = None
    released_at: str | None = None
    image_uri: str | None = None
    image_uris: dict[str, str] = Field(default_factory=dict)
    faces: list[CardFaceRecord] = Field(default_factory=list)
    legalities: dict[str, str] = Field(default_factory=dict)
    price_usd: float | None = None
    price_usd_foil: float | None = None
    tags: list[str] = Field(default_factory=list)
    purchase_links: CardPurchaseLinks = Field(default_factory=CardPurchaseLinks)


class CardDetailResponse(BaseModel):
    card: CardRecord


class CardSearchResult(BaseModel):
    name: str
    type_line: str
    mana_cost: str = ""
    image_uri: str | None = None
    colors: list[str] = Field(default_factory=list)
    color_identity: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class CardSearchResponse(BaseModel):
    cards: list[CardSearchResult]


class DataStatusResponse(BaseModel):
    card_source: Literal["database", "sample"]
    card_count: int
    archetype_source: Literal["database", "sample"]
    archetype_count: int
    database_url: str
    scryfall_ingested: bool


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
    commander_name: str | None = None
    playstyle_tags: list[str] = Field(default_factory=list)
    theme_tags: list[str] = Field(default_factory=list)
    budget: float | None = Field(default=None, ge=0)
    include_cards: list[str] = Field(default_factory=list)
    exclude_cards: list[str] = Field(default_factory=list)
    seed_cards: list[CardRef] = Field(default_factory=list)
    mode: ModeName = "constraint-aware"
    experience_level: ExperienceLevel = "beginner"
    prompt: str = ""


class RefineDeckRequest(BaseModel):
    deck: "DeckResponse"
    refinement_prompt: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatDeckRequest(BaseModel):
    deck: "DeckResponse"
    message: str
    history: list[ChatMessage] = Field(default_factory=list)


class ChatDeckResponse(BaseModel):
    reply: str
    suggested_refinement: str | None = None


class ValidateDeckRequest(BaseModel):
    format: FormatName
    mainboard: list[CardRef]
    sideboard: list[CardRef] = Field(default_factory=list)
    commander: str | None = None


class AnalyzeDeckRequest(BaseModel):
    format: FormatName
    mainboard: list[CardRef]
    sideboard: list[CardRef] = Field(default_factory=list)
    commander: str | None = None
    notes: str = ""
    deep_analysis: bool = True


class DiffDeckRequest(BaseModel):
    before: list[CardRef]
    after: list[CardRef]


class SaveDeckRequest(BaseModel):
    name: str = "Untitled deck"
    format: FormatName
    mainboard: list[CardRef]
    sideboard: list[CardRef] = Field(default_factory=list)
    commander: str | None = None
    notes: str = ""
    evaluation: dict = Field(default_factory=dict)


class EvaluateDeckRequest(BaseModel):
    format: FormatName
    mainboard: list[CardRef]
    sideboard: list[CardRef] = Field(default_factory=list)
    commander: str | None = None
    games: int = Field(default=200, ge=20, le=1000)
    seed: int = 1729


class ParseDecklistRequest(BaseModel):
    format: FormatName
    deck_text: str


class ParsedDecklistResponse(BaseModel):
    format: FormatName
    commander: str | None = None
    mainboard: list[CardRef] = Field(default_factory=list)
    sideboard: list[CardRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExportDeckRequest(BaseModel):
    deck: "DeckResponse"
    target: Literal["arena", "plain", "csv", "moxfield"] = "plain"


class ScoreBreakdown(BaseModel):
    legality: int
    mana: int
    synergy: int
    competitiveness: int
    role_balance: int = 0
    curve: int = 0
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


class DeckMechanic(BaseModel):
    label: str
    summary: str
    cards: list[str] = Field(default_factory=list)


class DeckSectionSummary(BaseModel):
    title: str
    summary: str
    bullets: list[str] = Field(default_factory=list)


class DeckRoleSummary(BaseModel):
    role: str
    total_cards: int
    key_cards: list[str] = Field(default_factory=list)


class ManaCurvePoint(BaseModel):
    mana_value: int
    card_count: int


SourceType = Literal["corpus", "fallback", "hybrid", "builtin"]

# Primary categorization for deck breakdown UI. Order matters: a card with
# multiple types (e.g. Artifact Creature) is bucketed by the first match in
# this precedence list.
PrimaryCardType = Literal[
    "Creature",
    "Planeswalker",
    "Instant",
    "Sorcery",
    "Enchantment",
    "Artifact",
    "Battle",
    "Land",
    "Other",
]


class DeckProvenance(BaseModel):
    """Honest, auditable record of where a generated deck came from.

    `source_type`:
      - `corpus`   — at least one archetype in the corpus matched the request
                     and seeded the deck (commander archetype or themed shell).
      - `fallback` — no corpus archetype matched; the deck was assembled from
                     the card pool by deterministic role/color/tag heuristics.
      - `hybrid`   — corpus shell seeded the build but most slots were filled
                     by fallback heuristics.

    `confidence` is in [0.0, 1.0]. For corpus sources it scales with the
    number and quality of supporting decks; for fallback it is conservative.
    """

    source_type: SourceType
    confidence: float = Field(ge=0, le=1)
    evidence_count: int = 0
    retrieved_from: list[str] = Field(default_factory=list)
    fallback_used: bool = False
    notes: list[str] = Field(default_factory=list)
    # When a blend or compose path triggered sim validation, this carries
    # the optimizer job id the frontend can poll. None means no sim
    # validation was queued (single-archetype matches don't need it).
    sim_validation_job_id: str | None = None


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
    sections: list[DeckSectionSummary] = Field(default_factory=list)
    mechanics: list[DeckMechanic] = Field(default_factory=list)
    role_summary: list[DeckRoleSummary] = Field(default_factory=list)
    mana_curve: list[ManaCurvePoint] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    source_archetypes: list[str] = Field(default_factory=list)
    selected_archetype: ArchetypeRecord | None = None
    provenance: DeckProvenance
    playstyle_tags: list[str] = Field(default_factory=list)
    theme_tags: list[str] = Field(default_factory=list)
    # Map of card name -> primary type bucket. Used by the UI to group the
    # mainboard/sideboard into Creatures / Spells / Lands sections.
    card_types: dict[str, PrimaryCardType] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_deck_sizes(self) -> "DeckResponse":
        if self.format == "commander" and sum(card.quantity for card in self.mainboard) != 99:
            raise ValueError("Commander decks must include 99 cards in the mainboard.")
        if self.format != "commander" and sum(card.quantity for card in self.mainboard) != 60:
            raise ValueError("Constructed decks must include 60 cards in the mainboard.")
        return self


class DeckAdviceGroup(BaseModel):
    keep_doing: list[str] = Field(default_factory=list)
    watch_out_for: list[str] = Field(default_factory=list)
    add_more_of: list[str] = Field(default_factory=list)
    cut_some_of: list[str] = Field(default_factory=list)
    possible_upgrades: list[str] = Field(default_factory=list)


class DeckImprovementSuggestion(BaseModel):
    category: str
    summary: str
    candidate_cards: list[str] = Field(default_factory=list)


class DeckSwapRecommendation(BaseModel):
    category: str
    cut_card: str
    add_card: str
    reason: str


class NearestShellComparison(BaseModel):
    shell_name: str
    confidence: float
    overlap_cards: list[str] = Field(default_factory=list)
    missing_cards: list[str] = Field(default_factory=list)
    off_plan_cards: list[str] = Field(default_factory=list)


class DeckAnalysisResponse(BaseModel):
    format: FormatName
    commander: str | None = None
    deck_health: Literal["well-structured", "promising but unfinished", "coherent but underpowered", "structurally flawed"]
    deck_health_explanation: str = ""
    inferred_style: str
    inferred_archetype: str
    similarity_label: str
    nearest_archetypes: list[str] = Field(default_factory=list)
    nearest_shell_comparison: NearestShellComparison | None = None
    game_plan_summary: str
    play_pattern_summary: str
    ai_coaching_note: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    synergy_observations: list[str] = Field(default_factory=list)
    package_observations: list[str] = Field(default_factory=list)
    advice: DeckAdviceGroup = Field(default_factory=DeckAdviceGroup)
    improvement_suggestions: list[DeckImprovementSuggestion] = Field(default_factory=list)
    swap_recommendations: list[DeckSwapRecommendation] = Field(default_factory=list)
    validation: ValidationResult
    role_summary: list[DeckRoleSummary] = Field(default_factory=list)
    mana_curve: list[ManaCurvePoint] = Field(default_factory=list)
    card_notes: list[DeckCardExplanation] = Field(default_factory=list)
    provenance: DeckProvenance
    deep_analysis_used: bool = False
    card_types: dict[str, PrimaryCardType] = Field(default_factory=dict)


class MetaSummaryResponse(BaseModel):
    format: FormatName
    archetypes: list[ArchetypeRecord]


class CommanderSearchResult(BaseModel):
    name: str
    colors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    strategy_summary: str
    popularity: float = 0
    support_depth: int = 0
    package_richness: int = 0
    ranking_score: float = 0
    image_uri: str | None = None


class CommanderProfile(BaseModel):
    card: CardRecord
    strategy_summary: str
    colors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    popularity: float = 0
    support_depth: int = 0
    package_richness: int = 0
    average_lands: float | None = None
    average_ramp: float | None = None
    average_draw: float | None = None
    average_interaction: float | None = None
    signature_cards: list[ArchetypePackage] = Field(default_factory=list)
    synergy_packages: list[ArchetypePackage] = Field(default_factory=list)
    ramp_package: list[ArchetypePackage] = Field(default_factory=list)
    draw_package: list[ArchetypePackage] = Field(default_factory=list)
    interaction_package: list[ArchetypePackage] = Field(default_factory=list)
    land_package: list[ArchetypePackage] = Field(default_factory=list)
    related_archetypes: list[str] = Field(default_factory=list)


class CommanderSearchResponse(BaseModel):
    commanders: list[CommanderSearchResult]


class CommanderProfileResponse(BaseModel):
    commander: CommanderProfile


RefineDeckRequest.model_rebuild()
ExportDeckRequest.model_rebuild()
