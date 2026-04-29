import type {
  CardDetailResponse,
  CardSearchResponse,
  CommanderProfileResponse,
  CommanderSearchResponse,
  DataStatusResponse,
  DeckAnalysisResponse,
  DeckResponse,
  FormatName,
  MetaSummaryResponse,
  ParsedDecklistResponse
} from "@/lib/types";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";

async function jsonOrThrow<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(detail?.detail ?? fallback);
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
