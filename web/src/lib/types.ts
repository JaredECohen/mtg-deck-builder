export type FormatName = "standard" | "modern" | "legacy" | "commander";

export type CardRef = {
  name: string;
  quantity: number;
};

export type CardRecord = {
  oracle_id?: string | null;
  name: string;
  mana_cost: string;
  mana_value: number;
  colors: string[];
  color_identity: string[];
  type_line: string;
  oracle_text: string;
  set_code?: string | null;
  released_at?: string | null;
  image_uri?: string | null;
  price_usd?: number | null;
  legalities: Record<string, string>;
  tags: string[];
};

export type CardDetailResponse = {
  card: CardRecord;
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
  sideboard_packages: ArchetypePackage[];
  top_weighted_decks: Array<Record<string, string | number>>;
  similarity_threshold?: number | null;
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
  total: number;
};

export type DeckCardExplanation = {
  name: string;
  role: string;
  reason: string;
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
  warnings: string[];
  source_archetypes: string[];
  selected_archetype?: ArchetypeRecord | null;
};

export type MetaSummaryResponse = {
  format: FormatName;
  archetypes: ArchetypeRecord[];
};
