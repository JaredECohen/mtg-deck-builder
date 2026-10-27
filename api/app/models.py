from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


FormatName = Literal["standard", "modern", "pioneer", "legacy", "commander"]
ModeName = Literal["fast-competitive", "constraint-aware", "creative-but-viable"]
ExperienceLevel = Literal["beginner", "expert"]
MatchType = Literal["bo1", "bo3"]
# Where a deck's evidence comes from: observed tournament results, or curated /
# synthesized templates that only encode an archetype's canonical shape.
EvidenceType = Literal["observed", "template"]


# Request-size bounds. Several endpoints are public and some spend LLM tokens,
# so every free-text field and list a client sends is capped. The web UI caps
# prompts at 1,500 characters, so these leave headroom for API callers.
PromptText = Annotated[str, Field(max_length=2_000)]
ChatText = Annotated[str, Field(max_length=8_000)]
CardName = Annotated[str, Field(min_length=1, max_length=200)]
CardNameList = Annotated[list[CardName], Field(max_length=100)]
TagList = Annotated[list[Annotated[str, Field(max_length=40)]], Field(max_length=20)]


class CardRef(BaseModel):
    name: CardName
    quantity: int = Field(ge=1, le=100)


# A decklist is at most a few hundred entries; anything larger is abuse.
CardRefList = Annotated[list[CardRef], Field(max_length=250)]


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
    # Most recent event date among the archetype's source decks (ISO date),
    # used for recency weighting and to timestamp meta claims.
    last_seen: str | None = None
    evidence: EvidenceType = "observed"


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
    # Backend name only ("sqlite", "postgresql"). This endpoint is public, so
    # the URL itself (path, host, credentials) is never exposed.
    database_backend: str
    scryfall_ingested: bool
    # Newest card release date in the DB: a proxy for how current the card,
    # legality and ban data is (the ingest records no timestamps).
    card_data_as_of: str | None = None
    # True when that date is older than DATA_STALE_DAYS (re-run ingest_scryfall).
    stale: bool = False


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
    colors: TagList = Field(default_factory=list)
    commander_name: CardName | None = None
    playstyle_tags: TagList = Field(default_factory=list)
    theme_tags: TagList = Field(default_factory=list)
    budget: float | None = Field(default=None, ge=0)
    include_cards: CardNameList = Field(default_factory=list)
    exclude_cards: CardNameList = Field(default_factory=list)
    seed_cards: CardRefList = Field(default_factory=list)
    mode: ModeName = "constraint-aware"
    experience_level: ExperienceLevel = "beginner"
    prompt: PromptText = ""
    match_type: MatchType = "bo3"
    # Commander power bracket target (WotC brackets 1-5). Ignored elsewhere.
    bracket: int | None = Field(default=None, ge=1, le=5)
    # Collection-aware building: owned cards are preferred and don't count
    # toward the budget.
    owned_cards: CardNameList = Field(default_factory=list)
    # Build from a specific retrieved shell (e.g. a listed alternative).
    archetype_name: Annotated[str, Field(max_length=200)] | None = None
    # Set by refine: the land seeds are the deck's existing mana base and are
    # kept as-is (generation from a prompt seeds archetype anchors instead,
    # whose lands go through the normal, budget-checked land build).
    preserve_mana_base: bool = False


class RefineDeckRequest(BaseModel):
    deck: "DeckResponse"
    refinement_prompt: PromptText


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: ChatText


class ChatDeckRequest(BaseModel):
    deck: "DeckResponse"
    message: PromptText
    history: list[ChatMessage] = Field(default_factory=list, max_length=40)


class ChatDeckResponse(BaseModel):
    reply: str
    suggested_refinement: str | None = None


class ValidateDeckRequest(BaseModel):
    format: FormatName
    mainboard: CardRefList
    sideboard: CardRefList = Field(default_factory=list)
    commander: CardName | None = None


class AnalyzeDeckRequest(BaseModel):
    format: FormatName
    mainboard: CardRefList
    sideboard: CardRefList = Field(default_factory=list)
    commander: CardName | None = None
    notes: PromptText = ""
    deep_analysis: bool = True


class DiffDeckRequest(BaseModel):
    before: CardRefList
    after: CardRefList


class SavedCardNote(BaseModel):
    name: Annotated[str, Field(max_length=200)]
    role: Annotated[str, Field(max_length=80)] = ""
    reason: Annotated[str, Field(max_length=2_000)] = ""


class SavedCurvePoint(BaseModel):
    mana_value: int = Field(ge=0, le=20)
    card_count: int = Field(ge=0, le=500)


_PrimaryCardType = Literal[
    "Creature", "Planeswalker", "Instant", "Sorcery", "Enchantment", "Artifact", "Battle", "Land", "Other"
]


class SaveDeckRequest(BaseModel):
    name: Annotated[str, Field(max_length=200)] = "Untitled deck"
    format: FormatName
    mainboard: CardRefList
    sideboard: CardRefList = Field(default_factory=list)
    commander: CardName | None = None
    notes: PromptText = ""
    evaluation: dict = Field(default_factory=dict)
    # public pages are indexable. unlisted links still open the deck and
    # are marked noindex, and they are left out of the sitemap.
    visibility: Literal["public", "unlisted"] = "public"
    colors: list[Annotated[str, Field(max_length=1)]] = Field(default_factory=list, max_length=5)
    price_usd: float | None = Field(default=None, ge=0, le=1_000_000)
    card_notes: list[SavedCardNote] = Field(default_factory=list, max_length=250)
    mana_curve: list[SavedCurvePoint] = Field(default_factory=list, max_length=21)
    card_types: dict[Annotated[str, Field(max_length=200)], _PrimaryCardType] = Field(default_factory=dict)
    key_cards: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=8)


class UpdateDeckRequest(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    visibility: Literal["public", "unlisted"] | None = None


class MagicLinkRequest(BaseModel):
    email: Annotated[str, Field(min_length=3, max_length=254)]


class VerifyLinkRequest(BaseModel):
    token: Annotated[str, Field(min_length=20, max_length=200)]


class EvaluateDeckRequest(BaseModel):
    format: FormatName
    mainboard: CardRefList
    sideboard: CardRefList = Field(default_factory=list)
    commander: CardName | None = None
    games: int = Field(default=200, ge=20, le=1000)
    seed: int = 1729


class ParseDecklistRequest(BaseModel):
    format: FormatName
    deck_text: Annotated[str, Field(max_length=100_000)]


class ParsedDecklistResponse(BaseModel):
    format: FormatName
    commander: str | None = None
    mainboard: list[CardRef] = Field(default_factory=list)
    sideboard: list[CardRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExportDeckRequest(BaseModel):
    deck: "DeckResponse"
    target: Literal["arena", "plain", "csv", "moxfield", "archidekt"] = "plain"


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


SourceType = Literal["corpus", "fallback", "hybrid", "builtin", "template"]

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
    # Spec §24 provenance: what reasoning added, what budget swapped, and
    # which requested cards could not be honored (and why).
    llm_added_cards: list[str] = Field(default_factory=list)
    budget_substitutions: list["BudgetSubstitution"] = Field(default_factory=list)
    dropped_includes: list["DroppedInclude"] = Field(default_factory=list)


class BudgetSubstitution(BaseModel):
    original: str
    replacement: str
    saved_usd: float | None = None


class DroppedInclude(BaseModel):
    name: str
    reason: Literal["unknown", "not_legal", "off_color", "over_budget", "bracket", "excluded", "no_room"]


class DeckConstraints(BaseModel):
    """The request constraints a deck was built under, so a refine can keep
    them (budget, excludes, ...) instead of silently dropping them."""

    budget: float | None = None
    include_cards: list[str] = Field(default_factory=list)
    exclude_cards: list[str] = Field(default_factory=list)
    owned_cards: list[str] = Field(default_factory=list)
    mode: ModeName = "constraint-aware"
    match_type: MatchType = "bo3"
    bracket: int | None = None
    experience_level: ExperienceLevel = "beginner"
    prompt: str = ""


class DeckAlternative(BaseModel):
    """A runner-up shell the user can build instead (spec §11F)."""

    name: str
    source_type: SourceType
    colors: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    key_cards: list[str] = Field(default_factory=list)
    summary: str = ""
    commander: str | None = None


class SideboardGuideEntry(BaseModel):
    card: str
    quantity: int
    purpose: str
    bring_in_against: list[str] = Field(default_factory=list)
    take_out: list[str] = Field(default_factory=list)


class MatchupNote(BaseModel):
    opponent: str
    outlook: Literal["favored", "even", "unfavored", "unknown"] = "unknown"
    note: str


class GamePlan(BaseModel):
    """Deterministic how-to-play guidance (spec §11G)."""

    summary: str = ""
    win_conditions: list[str] = Field(default_factory=list)
    opening_hand: list[str] = Field(default_factory=list)
    mulligan: list[str] = Field(default_factory=list)
    sideboard_guide: list[SideboardGuideEntry] = Field(default_factory=list)
    matchups: list[MatchupNote] = Field(default_factory=list)
    commander_packages: dict[str, list[str]] = Field(default_factory=dict)


class BracketAssessment(BaseModel):
    """Commander power bracket (WotC brackets 1-5) with the evidence."""

    estimated: int = Field(ge=1, le=5)
    target: int | None = None
    game_changers: list[str] = Field(default_factory=list)
    mass_land_denial: list[str] = Field(default_factory=list)
    extra_turns: list[str] = Field(default_factory=list)
    tutors: list[str] = Field(default_factory=list)
    two_card_combos: list[list[str]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    game_changers_as_of: str | None = None


class ColorSourcePoint(BaseModel):
    color: str
    sources: int
    pips: int


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
    # Stable id of the exact list (format, commander, main, side).
    deck_id: str = ""
    constraints: DeckConstraints = Field(default_factory=DeckConstraints)
    alternatives: list[DeckAlternative] = Field(default_factory=list)
    game_plan: GamePlan = Field(default_factory=GamePlan)
    bracket: BracketAssessment | None = None
    color_sources: list[ColorSourcePoint] = Field(default_factory=list)
    # Set by refine: the card-level diff against the previous version.
    changes: dict | None = None
    unpriced_cards: list[str] = Field(default_factory=list)
    # Price of the cards not in constraints.owned_cards.
    cost_to_complete_usd: float | None = None

    @model_validator(mode="after")
    def check_deck_sizes(self) -> "DeckResponse":
        if self.format == "commander" and sum(card.quantity for card in self.mainboard) != 99:
            raise ValueError("Commander decks must include 99 cards in the mainboard.")
        if self.format != "commander" and sum(card.quantity for card in self.mainboard) < 60:
            raise ValueError("Constructed decks must include at least 60 cards in the mainboard.")
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
    # Most recent event date across the format's corpus; meta claims are
    # timestamped (spec §26).
    as_of: str | None = None


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
    provenance: DeckProvenance


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
    provenance: DeckProvenance


class CommanderSearchResponse(BaseModel):
    commanders: list[CommanderSearchResult]


class CommanderProfileResponse(BaseModel):
    commander: CommanderProfile


class PreconSummary(BaseModel):
    id: str
    name: str
    commander: str | None = None
    commanders: list[str] = Field(default_factory=list)
    color_identity: list[str] = Field(default_factory=list)
    release_date: str | None = None
    set_code: str | None = None
    format: Literal["commander"] = "commander"


class PreconSearchResponse(BaseModel):
    precons: list[PreconSummary]


class PreconUpgradeRequest(BaseModel):
    precon_id: Annotated[str, Field(max_length=200)] | None = None
    deck_text: Annotated[str, Field(max_length=100_000)] | None = None
    budget_usd: float = Field(ge=0, le=5_000)
    # Bracket ceiling for the cards we add. 3 is "upgraded precon": Game
    # Changers are allowed up to three, mass land denial and extra turns are not.
    max_bracket: int | None = Field(default=3, ge=1, le=5)
    max_swaps: int = Field(default=12, ge=1, le=40)


class PreconSwap(BaseModel):
    rank: int
    cut: str
    cut_explanation: str
    add: str
    add_explanation: str
    add_price_usd: float
    score: float


class PreconUpgradeResponse(BaseModel):
    precon_id: str | None = None
    name: str
    commander: str | None = None
    commanders: list[str] = Field(default_factory=list)
    budget_usd: float
    total_cost_usd: float
    swaps: list[PreconSwap] = Field(default_factory=list)
    legality: ValidationResult
    bracket: BracketAssessment
    tcgplayer_cart_url: str | None = None
    warnings: list[str] = Field(default_factory=list)
    upgraded_mainboard: list[CardRef] = Field(default_factory=list)


RefineDeckRequest.model_rebuild()
ExportDeckRequest.model_rebuild()
DeckProvenance.model_rebuild()
