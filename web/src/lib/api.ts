import type {
  CardDetailResponse,
  CardSearchResponse,
  CommanderProfileResponse,
  CommanderSearchResponse,
  DataStatusResponse,
  DeckAnalysisResponse,
  DeckDiffResult,
  DeckResponse,
  FormatName,
  GenerationMode,
  JobRecord,
  MatchType,
  MetaSummaryResponse,
  OptimizerJobRequest,
  OptimizerJobResponse,
  ParsedDecklistResponse,
  PreconSummary,
  PreconUpgradeResponse
} from "@/lib/types";

// Every request goes through the same-origin proxy (app/api/backend), which
// forwards to the API and adds the server-side API key. No key is in the bundle.
export const API_BASE = "/api/backend";

const JSON_HEADERS = { "Content-Type": "application/json" } as const;

// Mirrors the backend's request bounds so oversized input is trimmed or fails
// here with a clear message instead of a 422.
export const MAX_PROMPT_CHARS = 2_000;
export const MAX_CARD_NAMES = 100;
export const MAX_DECKLIST_ENTRIES = 250;

function errorDetail(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  // FastAPI validation errors: [{loc, msg, ...}]
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { msg?: unknown; loc?: unknown };
    if (typeof first?.msg === "string") {
      const field = Array.isArray(first.loc) ? first.loc.filter((part) => part !== "body").join(".") : "";
      return field ? `${field}: ${first.msg}` : first.msg;
    }
  }
  return null;
}

async function jsonOrThrow<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) {
      throw new Error("The deck service needs an API key. Set MTG_API_KEY for the web server.");
    }
    if (response.status === 429) {
      throw new Error("Too many requests right now. Wait a moment and try again.");
    }
    // Non-JSON (e.g. HTML error pages) parses to null and uses the fallback.
    const body = await response.json().catch(() => null);
    throw new Error(errorDetail(body?.detail) ?? body?.error ?? body?.message ?? fallback);
  }
  return (await response.json()) as T;
}

function clampText(value: string | undefined, max = MAX_PROMPT_CHARS): string {
  return (value ?? "").slice(0, max);
}

/** Trim, de-duplicate (case-insensitively) and cap a list of card names. */
export function clampNames(names: string[] | undefined): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of names ?? []) {
    const name = raw.trim().slice(0, 200);
    const key = name.toLowerCase();
    if (!name || seen.has(key)) continue;
    seen.add(key);
    out.push(name);
    if (out.length >= MAX_CARD_NAMES) break;
  }
  return out;
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

export type { DeckDiffResult };

export type DeckVisibility = "public" | "unlisted";

export type SavedCardNote = { name: string; role: string; reason: string };

export type SavedDeck = {
  id: string;
  share_token: string;
  name: string;
  format: FormatName;
  commander: string | null;
  mainboard: CardRefInput[];
  sideboard: CardRefInput[];
  notes: string;
  evaluation: Partial<DeckEvaluation> | Record<string, never>;
  created_at: string;
  updated_at: string;
  visibility?: DeckVisibility;
  colors?: string[];
  price_usd?: number | null;
  card_notes?: SavedCardNote[];
  mana_curve?: { mana_value: number; card_count: number }[];
  card_types?: Record<string, string>;
  key_cards?: string[];
};

export type SimilarCardsResponse = {
  card: string;
  mode: string;
  similar: { name: string; score: number }[];
};

export type GenerateDeckInput = {
  format: FormatName;
  colors: string[];
  commander_name?: string;
  playstyle_tags: string[];
  theme_tags: string[];
  budget?: number;
  experience_level?: "beginner" | "expert";
  prompt?: string;
  // Expert controls. Left undefined, the backend defaults apply.
  mode?: GenerationMode;
  match_type?: MatchType;
  bracket?: number | null;
  include_cards?: string[];
  exclude_cards?: string[];
  owned_cards?: string[];
  /** Build from a specific retrieved shell (an "Also consider" alternative). */
  archetype_name?: string | null;
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
  // Only fields the user actually set are sent, so the backend's defaults
  // (not hidden client defaults) apply to everything else.
  const body: Record<string, unknown> = {
    format: input.format,
    colors: input.colors,
    commander_name: input.commander_name,
    playstyle_tags: input.playstyle_tags,
    theme_tags: input.theme_tags,
    budget: input.budget,
    experience_level: input.experience_level ?? "beginner",
    prompt: clampText(input.prompt)
  };
  if (input.mode) body.mode = input.mode;
  if (input.match_type) body.match_type = input.match_type;
  if (input.bracket != null) body.bracket = input.bracket;
  if (input.include_cards?.length) body.include_cards = clampNames(input.include_cards);
  if (input.exclude_cards?.length) body.exclude_cards = clampNames(input.exclude_cards);
  if (input.owned_cards?.length) body.owned_cards = clampNames(input.owned_cards);
  if (input.archetype_name) body.archetype_name = input.archetype_name.slice(0, 200);
  const response = await fetch(`${API_BASE}/v1/decks/generate`, {
    method: "POST",
    headers: JSON_HEADERS,
    signal,
    body: JSON.stringify(body)
  });
  return jsonOrThrow<DeckResponse>(response, "Generation failed");
}

export async function refineDeck(deck: DeckResponse, prompt: string, signal?: AbortSignal): Promise<DeckResponse> {
  const response = await fetch(`${API_BASE}/v1/decks/refine`, {
    method: "POST",
    headers: JSON_HEADERS,
    signal,
    body: JSON.stringify({ deck, refinement_prompt: clampText(prompt) })
  });
  return jsonOrThrow<DeckResponse>(response, "Refinement failed");
}

export type ChatTurn = { role: "user" | "assistant"; content: string };
export type ChatDeckResponse = { reply: string; suggested_refinement: string | null };

export async function chatAboutDeck(
  deck: DeckResponse,
  message: string,
  history: ChatTurn[],
  signal?: AbortSignal
): Promise<ChatDeckResponse> {
  const response = await fetch(`${API_BASE}/v1/decks/chat`, {
    method: "POST",
    headers: JSON_HEADERS,
    signal,
    // The backend accepts at most 40 turns of history.
    body: JSON.stringify({ deck, message: clampText(message), history: history.slice(-40) })
  });
  return jsonOrThrow<ChatDeckResponse>(response, "Deck chat failed");
}

export type ExportTarget = "arena" | "plain" | "csv" | "moxfield" | "archidekt";

export async function exportDeck(
  deck: DeckResponse,
  target: ExportTarget,
  signal?: AbortSignal
): Promise<{ content: string; target: ExportTarget }> {
  const response = await fetch(`${API_BASE}/v1/decks/export`, {
    method: "POST",
    headers: JSON_HEADERS,
    signal,
    body: JSON.stringify({ deck, target })
  });
  return jsonOrThrow<{ content: string; target: ExportTarget }>(response, "Export failed");
}

export async function analyzeDeck(
  payload: {
    format: FormatName;
    commander?: string;
    mainboard: { name: string; quantity: number }[];
    sideboard: { name: string; quantity: number }[];
    notes: string;
    deep_analysis?: boolean;
  },
  signal?: AbortSignal
): Promise<DeckAnalysisResponse> {
  if (payload.mainboard.length > MAX_DECKLIST_ENTRIES || payload.sideboard.length > MAX_DECKLIST_ENTRIES) {
    throw new Error(`A decklist can have at most ${MAX_DECKLIST_ENTRIES} different cards.`);
  }
  const response = await fetch(`${API_BASE}/v1/decks/analyze`, {
    method: "POST",
    headers: JSON_HEADERS,
    signal,
    body: JSON.stringify({ ...payload, notes: clampText(payload.notes) })
  });
  return jsonOrThrow<DeckAnalysisResponse>(response, "Analysis failed");
}

export async function parseDeckText(format: FormatName, deck_text: string, signal?: AbortSignal): Promise<ParsedDecklistResponse> {
  const response = await fetch(`${API_BASE}/v1/decks/parse`, {
    method: "POST",
    headers: JSON_HEADERS,
    signal,
    body: JSON.stringify({ format, deck_text: deck_text.slice(0, 100_000) })
  });
  return jsonOrThrow<ParsedDecklistResponse>(response, "Deck import failed");
}

export async function searchCards(query: string, format: FormatName | null, signal?: AbortSignal): Promise<CardSearchResponse> {
  // No format yet: search the whole card pool.
  const params = new URLSearchParams({ query: query.trim(), ...(format ? { format } : {}) });
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

export async function fetchCardDetail(name: string, signal?: AbortSignal): Promise<CardDetailResponse> {
  const response = await fetch(`${API_BASE}/v1/cards/${encodeURIComponent(name)}`, { signal });
  return jsonOrThrow<CardDetailResponse>(response, "Could not load card details.");
}

export async function fetchMetaSummary(format: FormatName, signal?: AbortSignal): Promise<MetaSummaryResponse> {
  const response = await fetch(`${API_BASE}/v1/meta/summary?format=${format}`, { signal });
  return jsonOrThrow<MetaSummaryResponse>(response, "Meta summary failed");
}

export async function submitOptimizerJob(payload: OptimizerJobRequest): Promise<OptimizerJobResponse> {
  const response = await fetch(`${API_BASE}/v1/jobs/optimize`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload)
  });
  return jsonOrThrow<OptimizerJobResponse>(response, "Optimizer submission failed");
}

export async function fetchJob(jobId: string): Promise<JobRecord> {
  const response = await fetch(`${API_BASE}/v1/jobs/${encodeURIComponent(jobId)}`);
  return jsonOrThrow<JobRecord>(response, "Job poll failed");
}

export async function evaluateDeck(
  payload: {
    format: FormatName;
    mainboard: CardRefInput[];
    sideboard?: CardRefInput[];
    commander?: string;
    games?: number;
    seed?: number;
  },
  signal?: AbortSignal
): Promise<DeckEvaluation> {
  const response = await fetch(`${API_BASE}/v1/decks/evaluate`, {
    method: "POST",
    headers: JSON_HEADERS,
    signal,
    body: JSON.stringify(payload)
  });
  return jsonOrThrow<DeckEvaluation>(response, "Deck evaluation failed");
}

export async function diffDecks(before: CardRefInput[], after: CardRefInput[]): Promise<DeckDiffResult> {
  const response = await fetch(`${API_BASE}/v1/decks/diff`, {
    method: "POST",
    headers: JSON_HEADERS,
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
  visibility?: DeckVisibility;
  colors?: string[];
  price_usd?: number | null;
  card_notes?: SavedCardNote[];
  mana_curve?: { mana_value: number; card_count: number }[];
  card_types?: Record<string, string>;
  key_cards?: string[];
}): Promise<SavedDeck> {
  const response = await fetch(`${API_BASE}/v1/decks/save`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify({ ...payload, name: payload.name.slice(0, 200), notes: clampText(payload.notes) })
  });
  return jsonOrThrow<SavedDeck>(response, "Saving deck failed");
}

export async function fetchDeckHistory(limit = 50): Promise<SavedDeck[]> {
  const response = await fetch(`${API_BASE}/v1/decks/history?limit=${limit}`);
  const body = await jsonOrThrow<{ decks: SavedDeck[] }>(response, "Could not load deck history");
  return body.decks;
}

export async function fetchSharedDeck(token: string, signal?: AbortSignal): Promise<SavedDeck> {
  const response = await fetch(`${API_BASE}/v1/decks/shared/${encodeURIComponent(token)}`, { signal });
  return jsonOrThrow<SavedDeck>(response, "Shared deck not found");
}

export async function fetchSavedDeck(id: string): Promise<SavedDeck> {
  const response = await fetch(`${API_BASE}/v1/decks/saved/${encodeURIComponent(id)}`);
  return jsonOrThrow<SavedDeck>(response, "Saved deck not found");
}

export async function deleteSavedDeck(id: string): Promise<void> {
  const response = await fetch(`${API_BASE}/v1/decks/saved/${encodeURIComponent(id)}`, { method: "DELETE" });
  await jsonOrThrow<{ deleted: string }>(response, "Could not delete the saved deck");
}

export async function updateSavedDeck(
  id: string,
  patch: { name?: string; visibility?: DeckVisibility }
): Promise<SavedDeck> {
  const response = await fetch(`${API_BASE}/v1/decks/saved/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: JSON_HEADERS,
    body: JSON.stringify(patch)
  });
  return jsonOrThrow<SavedDeck>(response, "Could not update the saved deck");
}

/** Similar cards, optionally restricted to cards legal in `format` and inside `colors`. */
export async function fetchPrecons(query = "", limit = 8, signal?: AbortSignal): Promise<PreconSummary[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (query.trim()) params.set("q", query.trim());
  const response = await fetch(`${API_BASE}/v1/commander/precons?${params.toString()}`, { signal });
  const body = await jsonOrThrow<{ precons: PreconSummary[] }>(response, "Precon search failed");
  return body.precons;
}

export async function upgradePrecon(payload: {
  precon_id?: string;
  deck_text?: string;
  budget_usd: number;
  max_bracket?: number;
}): Promise<PreconUpgradeResponse> {
  const response = await fetch(`${API_BASE}/v1/commander/precon-upgrade`, {
    method: "POST",
    headers: JSON_HEADERS,
    body: JSON.stringify(payload)
  });
  return jsonOrThrow<PreconUpgradeResponse>(response, "Precon upgrade failed");
}

export async function fetchSimilarCards(
  name: string,
  options: { k?: number; format?: FormatName; colors?: string[] } = {},
  signal?: AbortSignal
): Promise<SimilarCardsResponse> {
  const params = new URLSearchParams({ k: String(options.k ?? 8) });
  if (options.format) params.set("format", options.format);
  if (options.colors) params.set("colors", options.colors.join(","));
  const response = await fetch(`${API_BASE}/v1/cards/${encodeURIComponent(name)}/similar?${params.toString()}`, { signal });
  return jsonOrThrow<SimilarCardsResponse>(response, "Similar-card lookup failed");
}
