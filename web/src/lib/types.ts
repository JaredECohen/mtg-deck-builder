export type FormatName = "standard" | "modern" | "legacy" | "commander";

export type CardRef = {
  name: string;
  quantity: number;
};

export type CardFaceRecord = {
  name?: string | null;
  mana_cost: string;
  type_line: string;
  oracle_text: string;
  image_uri?: string | null;
};

export type CardPurchaseLinks = {
  scryfall?: string | null;
  amazon_search?: string | null;
};

export type CardRecord = {
  oracle_id?: string | null;
  scryfall_id?: string | null;
  name: string;
  normalized_name?: string | null;
  mana_cost: string;
  mana_value: number;
  colors: string[];
  color_identity: string[];
  type_line: string;
  oracle_text: string;
  keywords: string[];
  layout?: string | null;
  rarity?: string | null;
  set_code?: string | null;
  released_at?: string | null;
  image_uri?: string | null;
  image_uris: Record<string, string>;
  faces: CardFaceRecord[];
  price_usd?: number | null;
  price_usd_foil?: number | null;
  legalities: Record<string, string>;
  tags: string[];
  purchase_links: CardPurchaseLinks;
};

export type CardDetailResponse = {
  card: CardRecord;
};

export type CardSearchResult = {
  name: string;
  type_line: string;
  mana_cost: string;
  image_uri?: string | null;
  colors: string[];
  color_identity: string[];
  tags: string[];
};

export type CardSearchResponse = {
  cards: CardSearchResult[];
};

export type ArchetypePackage = {
  name: string;
  inclusion_rate?: number | null;
  average_quantity?: number | null;
  tags: string[];
};

export type ArchetypeMetadata = {
  signature_sample?: string | null;
  source_event_names: string[];
  sample_deck_ids: string[];
  core_cards: ArchetypePackage[];
  flex_cards: ArchetypePackage[];
  land_packages: ArchetypePackage[];
  sideboard_packages: ArchetypePackage[];
  matchup_tech_packages: ArchetypePackage[];
  top_weighted_decks: Array<Record<string, string | number>>;
  similarity_threshold?: number | null;
  archetype_type?: "constructed" | "commander";
  color_profile: string[];
  commander_package?: {
    commander_name: string;
    popularity: number;
    support_depth: number;
    average_lands?: number | null;
    average_ramp?: number | null;
    average_draw?: number | null;
    average_interaction?: number | null;
    signature_cards: ArchetypePackage[];
    synergy_packages: ArchetypePackage[];
    ramp_package: ArchetypePackage[];
    draw_package: ArchetypePackage[];
    interaction_package: ArchetypePackage[];
    land_package: ArchetypePackage[];
  } | null;
};

export type ArchetypeRecord = {
  id: string;
  name: string;
  format: FormatName;
  colors: string[];
  tags: string[];
  strategy: string;
  mainboard: CardRef[];
  sideboard: CardRef[];
  commander?: string | null;
  source_count: number;
  avg_placement?: number | null;
  metadata: ArchetypeMetadata;
};

export type ScoreBreakdown = {
  legality: number;
  mana: number;
  synergy: number;
  prompt_fit: number;
  competitiveness: number;
  budget_fit: number;
  role_balance: number;
  curve: number;
  total: number;
};

export type DeckCardExplanation = {
  name: string;
  role: string;
  reason: string;
};

export type DeckMechanic = {
  label: string;
  summary: string;
  cards: string[];
};

export type DeckSectionSummary = {
  title: string;
  summary: string;
  bullets: string[];
};

export type DeckRoleSummary = {
  role: string;
  total_cards: number;
  key_cards: string[];
};

export type ManaCurvePoint = {
  mana_value: number;
  card_count: number;
};

export type DeckResponse = {
  format: FormatName;
  title: string;
  colors: string[];
  strategy_summary: string;
  commander?: string | null;
  mainboard: CardRef[];
  sideboard: CardRef[];
  estimated_price_usd?: number | null;
  is_legal: boolean;
  validation_errors: string[];
  score: ScoreBreakdown;
  explanation: string[];
  card_notes: DeckCardExplanation[];
  sections: DeckSectionSummary[];
  mechanics: DeckMechanic[];
  role_summary: DeckRoleSummary[];
  mana_curve: ManaCurvePoint[];
  warnings: string[];
  source_archetypes: string[];
  selected_archetype?: ArchetypeRecord | null;
  playstyle_tags: string[];
  theme_tags: string[];
};

export type MetaSummaryResponse = {
  format: FormatName;
  archetypes: ArchetypeRecord[];
};

export type DataStatusResponse = {
  card_source: "database" | "sample";
  card_count: number;
  archetype_source: "database" | "sample";
  archetype_count: number;
  database_url: string;
  scryfall_ingested: boolean;
};

export type DeckAdviceGroup = {
  keep_doing: string[];
  watch_out_for: string[];
  add_more_of: string[];
  cut_some_of: string[];
  possible_upgrades: string[];
};

export type DeckImprovementSuggestion = {
  category: string;
  summary: string;
  candidate_cards: string[];
};

export type DeckSwapRecommendation = {
  category: string;
  cut_card: string;
  add_card: string;
  reason: string;
};

export type DeckAnalysisResponse = {
  format: FormatName;
  commander?: string | null;
  deck_health: "well-structured" | "promising but unfinished" | "coherent but underpowered" | "structurally flawed";
  deck_health_explanation: string;
  inferred_style: string;
  inferred_archetype: string;
  similarity_label: string;
  nearest_archetypes: string[];
  nearest_shell_comparison?: {
    shell_name: string;
    confidence: number;
    overlap_cards: string[];
    missing_cards: string[];
    off_plan_cards: string[];
  } | null;
  game_plan_summary: string;
  play_pattern_summary: string;
  ai_coaching_note: string;
  strengths: string[];
  weaknesses: string[];
  synergy_observations: string[];
  package_observations: string[];
  advice: DeckAdviceGroup;
  improvement_suggestions: DeckImprovementSuggestion[];
  swap_recommendations: DeckSwapRecommendation[];
  validation: {
    is_legal: boolean;
    errors: string[];
    warnings: string[];
    score: ScoreBreakdown;
  };
  role_summary: DeckRoleSummary[];
  mana_curve: ManaCurvePoint[];
  card_notes: DeckCardExplanation[];
};

export type ParsedDecklistResponse = {
  format: FormatName;
  commander?: string | null;
  mainboard: CardRef[];
  sideboard: CardRef[];
  warnings: string[];
};

export type CommanderSearchResult = {
  name: string;
  colors: string[];
  tags: string[];
  strategy_summary: string;
  popularity: number;
  support_depth: number;
  package_richness: number;
  ranking_score: number;
  image_uri?: string | null;
};

export type CommanderProfile = {
  card: CardRecord;
  strategy_summary: string;
  colors: string[];
  tags: string[];
  popularity: number;
  support_depth: number;
  package_richness: number;
  average_lands?: number | null;
  average_ramp?: number | null;
  average_draw?: number | null;
  average_interaction?: number | null;
  signature_cards: ArchetypePackage[];
  synergy_packages: ArchetypePackage[];
  ramp_package: ArchetypePackage[];
  draw_package: ArchetypePackage[];
  interaction_package: ArchetypePackage[];
  land_package: ArchetypePackage[];
  related_archetypes: string[];
};

export type CommanderSearchResponse = {
  commanders: CommanderSearchResult[];
};

export type CommanderProfileResponse = {
  commander: CommanderProfile;
};
