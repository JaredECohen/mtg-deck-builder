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

async function jsonOrThrow<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) {
    // Non-JSON (e.g. HTML error pages) parses to null and uses the fallback.
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? detail?.error ?? detail?.message ?? fallback);
  }
  return (await response.json()) as T;
}

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
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify({ deck, message, history })
  });
  return jsonOrThrow<ChatDeckResponse>(response, "Deck chat failed");
}

export type SavedDeckSummary = {
  id: string;
  title: string;
  format: FormatName;
  created_at: string;
};

export type SavedDeckDetail = SavedDeckSummary & { deck: DeckResponse; chat_history?: ChatTurn[] };

export async function saveDeck(sessionId: string, deck: DeckResponse, chatHistory: ChatTurn[] = []): Promise<SavedDeckSummary> {
  const response = await fetch(`${API_BASE}/v1/decks/save`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, deck, chat_history: chatHistory })
  });
  return jsonOrThrow<SavedDeckSummary>(response, "Save deck failed");
}

export async function listSavedDecks(sessionId: string): Promise<SavedDeckSummary[]> {
  const params = new URLSearchParams({ session_id: sessionId });
  const response = await fetch(`${API_BASE}/v1/decks/saved?${params.toString()}`);
  const payload = await jsonOrThrow<{ decks: SavedDeckSummary[] }>(response, "List saved decks failed");
  return payload.decks;
}

export async function loadSavedDeck(deckId: string): Promise<SavedDeckDetail> {
  const response = await fetch(`${API_BASE}/v1/decks/saved/${encodeURIComponent(deckId)}`);
  return jsonOrThrow<SavedDeckDetail>(response, "Load saved deck failed");
}

export async function deleteSavedDeck(deckId: string, sessionId: string): Promise<void> {
  const params = new URLSearchParams({ session_id: sessionId });
  const response = await fetch(`${API_BASE}/v1/decks/saved/${encodeURIComponent(deckId)}?${params.toString()}`, {
    method: "DELETE"
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? detail?.error ?? detail?.message ?? "Delete failed");
  }
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

export async function parseDeckText(format: FormatName, deck_text: string, signal?: AbortSignal): Promise<ParsedDecklistResponse> {
  const response = await fetch(`${API_BASE}/v1/decks/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal,
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
