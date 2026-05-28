import type {
  CardDetailResponse,
  CardSearchResponse,
  CommanderProfileResponse,
  CommanderSearchResponse,
  DataStatusResponse,
  DeckAnalysisResponse,
  DeckResponse,
  FormatName,
  JobRecord,
  MetaSummaryResponse,
  OptimizerJobRequest,
  OptimizerJobResponse,
  ParsedDecklistResponse
} from "@/lib/types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
const API_KEY = process.env.NEXT_PUBLIC_API_KEY;

/** JSON headers plus the optional X-API-Key when configured. */
function jsonHeaders(): Record<string, string> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  return headers;
}

async function jsonOrThrow<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? fallback);
  }
  return (await response.json()) as T;
}

export type CardRefInput = { name: string; quantity: number };

export type DeckEvaluation = {
  format_id: string;
  archetype: string;
  games: number;
  win_rate: number;
  win_rate_ci: [number, number];
  avg_kill_turn: number;
  kill_turn_stdev: number;
  p25_kill_turn: number;
  p75_kill_turn: number;
  flood_resistance: number;
  screw_resistance: number;
  interaction_resilience: number;
  inevitability: number;
  consistency: number;
  card_advantage_density: number;
  notes: string[];
  cards_evaluated: number;
  unresolved_cards: string[];
};

export type DeckDiffResult = {
  added: { name: string; quantity: number }[];
  removed: { name: string; quantity: number }[];
  increased: { name: string; from: number; to: number; delta: number }[];
  decreased: { name: string; from: number; to: number; delta: number }[];
  unchanged: { name: string; quantity: number }[];
  summary: { cards_added: number; cards_removed: number; total_changes: number; identical: boolean };
};

export type SavedDeck = {
  id: string;
  share_token: string;
  owner: string | null;
  name: string;
  format: FormatName;
  commander: string | null;
  mainboard: CardRefInput[];
  sideboard: CardRefInput[];
  notes: string;
  evaluation: Partial<DeckEvaluation> | Record<string, never>;
  created_at: string;
  updated_at: string;
};

export type SimilarCardsResponse = {
  card: string;
  mode: "pgvector" | "lexical";
  similar: { name: string; score: number }[];
};

export type GenerateDeckInput = {
  format: FormatName;
  colors: string[];
  commander_name?: string;
  playstyle_tags: string[];
  theme_tags: string[];
  budget?: number;
  prompt?: string;
};

export async function fetchDataStatus(signal?: AbortSignal): Promise<DataStatusResponse | null> {
  try {
    const response = await fetch(`${API_BASE}/api/data-status`, { signal });
    if (!response.ok) return null;
    return (await response.json()) as DataStatusResponse;
  } catch {
    return null;
  }
}

export async function generateDeck(input: GenerateDeckInput, signal?: AbortSignal): Promise<DeckResponse> {
  const response = await fetch(`${API_BASE}/v1/decks/generate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify({
      format: input.format,
      colors: input.colors,
      commander_name: input.commander_name,
      playstyle_tags: input.playstyle_tags,
      theme_tags: input.theme_tags,
      budget: input.budget,
      mode: "constraint-aware",
      experience_level: "beginner",
      prompt: input.prompt ?? ""
    })
  });
  return jsonOrThrow<DeckResponse>(response, "Generation failed");
}

export async function refineDeck(deck: DeckResponse, prompt: string, signal?: AbortSignal): Promise<DeckResponse> {
  const response = await fetch(`${API_BASE}/v1/decks/refine`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify({ deck, refinement_prompt: prompt })
  });
  return jsonOrThrow<DeckResponse>(response, "Refinement failed");
}

export type ExportTarget = "arena" | "plain" | "csv" | "moxfield";

export async function exportDeck(deck: DeckResponse, target: ExportTarget): Promise<{ content: string; target: ExportTarget }> {
  const response = await fetch(`${API_BASE}/v1/decks/export`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ deck, target })
  });
  return jsonOrThrow<{ content: string; target: ExportTarget }>(response, "Export failed");
}

export async function analyzeDeck(payload: {
  format: FormatName;
  commander?: string;
  mainboard: { name: string; quantity: number }[];
  sideboard: { name: string; quantity: number }[];
  notes: string;
  deep_analysis?: boolean;
}): Promise<DeckAnalysisResponse> {
  const response = await fetch(`${API_BASE}/v1/decks/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return jsonOrThrow<DeckAnalysisResponse>(response, "Analysis failed");
}

export async function parseDeckText(format: FormatName, deck_text: string): Promise<ParsedDecklistResponse> {
  const response = await fetch(`${API_BASE}/v1/decks/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ format, deck_text })
  });
  return jsonOrThrow<ParsedDecklistResponse>(response, "Deck import failed");
}

export async function searchCards(query: string, format: FormatName, signal?: AbortSignal): Promise<CardSearchResponse> {
  const params = new URLSearchParams({ query: query.trim(), format });
  const response = await fetch(`${API_BASE}/v1/cards?${params.toString()}`, { signal });
  return jsonOrThrow<CardSearchResponse>(response, "Card search failed");
}

export async function searchCommanders(
  filters: { colors: string[]; playstyle_tags: string[]; theme_tags: string[]; search: string; sort: string; limit: number },
  signal?: AbortSignal
): Promise<CommanderSearchResponse> {
  const params = new URLSearchParams();
  if (filters.colors.length) params.set("colors", filters.colors.join(","));
  if (filters.playstyle_tags.length) params.set("playstyle_tags", filters.playstyle_tags.join(","));
  if (filters.theme_tags.length) params.set("theme_tags", filters.theme_tags.join(","));
  if (filters.search.trim()) params.set("search", filters.search.trim());
  params.set("sort", filters.sort);
  params.set("limit", String(filters.limit));
  const response = await fetch(`${API_BASE}/v1/commanders?${params.toString()}`, { signal });
  return jsonOrThrow<CommanderSearchResponse>(response, "Commander search failed");
}

export async function fetchCommanderProfile(name: string, signal?: AbortSignal): Promise<CommanderProfileResponse> {
  const response = await fetch(`${API_BASE}/v1/commanders/${encodeURIComponent(name)}`, { signal });
  return jsonOrThrow<CommanderProfileResponse>(response, "Commander profile failed");
}

export async function fetchCardDetail(name: string): Promise<CardDetailResponse> {
  const response = await fetch(`${API_BASE}/v1/cards/${encodeURIComponent(name)}`);
  return jsonOrThrow<CardDetailResponse>(response, "Could not load card details.");
}

export async function fetchMetaSummary(format: FormatName, signal?: AbortSignal): Promise<MetaSummaryResponse> {
  const response = await fetch(`${API_BASE}/v1/meta/summary?format=${format}`, { signal });
  return jsonOrThrow<MetaSummaryResponse>(response, "Meta summary failed");
}

export async function submitOptimizerJob(payload: OptimizerJobRequest): Promise<OptimizerJobResponse> {
  const response = await fetch(`${API_BASE}/v1/jobs/optimize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return jsonOrThrow<OptimizerJobResponse>(response, "Optimizer submission failed");
}

export async function fetchJob(jobId: string): Promise<JobRecord> {
  const response = await fetch(`${API_BASE}/v1/jobs/${encodeURIComponent(jobId)}`);
  return jsonOrThrow<JobRecord>(response, "Job poll failed");
}

export async function evaluateDeck(payload: {
  format: FormatName;
  mainboard: CardRefInput[];
  sideboard?: CardRefInput[];
  commander?: string;
  games?: number;
  seed?: number;
}, signal?: AbortSignal): Promise<DeckEvaluation> {
  const response = await fetch(`${API_BASE}/v1/decks/evaluate`, {
    method: "POST",
    headers: jsonHeaders(),
    signal,
    body: JSON.stringify(payload)
  });
  return jsonOrThrow<DeckEvaluation>(response, "Deck evaluation failed");
}

export async function diffDecks(before: CardRefInput[], after: CardRefInput[]): Promise<DeckDiffResult> {
  const response = await fetch(`${API_BASE}/v1/decks/diff`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify({ before, after })
  });
  return jsonOrThrow<DeckDiffResult>(response, "Deck diff failed");
}

export async function saveDeck(payload: {
  name: string;
  format: FormatName;
  mainboard: CardRefInput[];
  sideboard?: CardRefInput[];
  commander?: string;
  notes?: string;
  evaluation?: Partial<DeckEvaluation>;
}): Promise<SavedDeck> {
  const response = await fetch(`${API_BASE}/v1/decks/save`, {
    method: "POST",
    headers: jsonHeaders(),
    body: JSON.stringify(payload)
  });
  return jsonOrThrow<SavedDeck>(response, "Saving deck failed");
}

export async function fetchDeckHistory(limit = 50): Promise<SavedDeck[]> {
  const response = await fetch(`${API_BASE}/v1/decks/history?limit=${limit}`, { headers: jsonHeaders() });
  const body = await jsonOrThrow<{ decks: SavedDeck[] }>(response, "Could not load deck history");
  return body.decks;
}

export async function fetchSharedDeck(token: string): Promise<SavedDeck> {
  const response = await fetch(`${API_BASE}/v1/decks/shared/${encodeURIComponent(token)}`);
  return jsonOrThrow<SavedDeck>(response, "Shared deck not found");
}

export async function fetchSimilarCards(name: string, k = 10): Promise<SimilarCardsResponse> {
  const response = await fetch(`${API_BASE}/v1/cards/${encodeURIComponent(name)}/similar?k=${k}`);
  return jsonOrThrow<SimilarCardsResponse>(response, "Similar-card lookup failed");
}
