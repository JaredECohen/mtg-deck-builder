import type { CardTypeMap, PrimaryCardType } from "@/lib/types";

export type PublicCardNote = { name: string; role?: string; reason?: string };

export type PublicDeck = {
  id: string;
  share_token: string;
  name: string;
  format: string;
  commander: string | null;
  mainboard: { name: string; quantity: number }[];
  sideboard: { name: string; quantity: number }[];
  notes: string;
  visibility: "public" | "unlisted";
  colors: string[];
  price_usd: number | null;
  card_notes: PublicCardNote[];
  mana_curve: { mana_value: number; card_count: number }[];
  card_types: Record<string, string>;
  key_cards: string[];
  updated_at: string;
};

const TOKEN_RE = /^[A-Za-z0-9_-]{8,80}$/;

const CARD_TYPES = new Set<PrimaryCardType>([
  "Creature",
  "Planeswalker",
  "Instant",
  "Sorcery",
  "Enchantment",
  "Artifact",
  "Battle",
  "Land",
  "Other"
]);

const FORMAT_LABELS: Record<string, string> = {
  standard: "Standard",
  modern: "Modern",
  pioneer: "Pioneer",
  legacy: "Legacy",
  commander: "Commander"
};

export const COLOR_LABELS: Record<string, string> = {
  W: "White",
  U: "Blue",
  B: "Black",
  R: "Red",
  G: "Green",
  C: "Colorless"
};

export function isShareToken(token: string): boolean {
  return TOKEN_RE.test(token);
}

export function formatLabel(format: string): string {
  return FORMAT_LABELS[format] ?? format;
}

export function formatPrice(price: number | null | undefined): string | null {
  if (price == null || !Number.isFinite(price)) return null;
  return `$${price.toFixed(2)}`;
}

export function deckBlurb(deck: PublicDeck): string {
  const bits = [formatLabel(deck.format)];
  if (deck.commander) bits.push(deck.commander);
  const price = formatPrice(deck.price_usd);
  if (price) bits.push(price);
  if (deck.key_cards.length) bits.push(deck.key_cards.slice(0, 4).join(", "));
  else if (deck.notes) bits.push(deck.notes);
  const text = bits.join(" · ");
  return text.length > 200 ? `${text.slice(0, 197)}...` : text;
}

export function cardTypeMap(raw: Record<string, string> | undefined): CardTypeMap {
  const map: CardTypeMap = {};
  for (const [name, type] of Object.entries(raw ?? {})) {
    if (CARD_TYPES.has(type as PrimaryCardType)) map[name] = type as PrimaryCardType;
  }
  return map;
}

function asDeck(raw: Partial<PublicDeck> & { share_token: string; name: string; format: string }): PublicDeck {
  return {
    id: raw.id ?? "",
    share_token: raw.share_token,
    name: raw.name,
    format: raw.format,
    commander: raw.commander ?? null,
    mainboard: raw.mainboard ?? [],
    sideboard: raw.sideboard ?? [],
    notes: raw.notes ?? "",
    visibility: raw.visibility === "unlisted" ? "unlisted" : "public",
    colors: raw.colors ?? [],
    price_usd: raw.price_usd ?? null,
    card_notes: raw.card_notes ?? [],
    mana_curve: raw.mana_curve ?? [],
    card_types: raw.card_types ?? {},
    key_cards: raw.key_cards ?? [],
    updated_at: raw.updated_at ?? ""
  };
}

function apiBase(): string | null {
  const base = process.env.API_BASE || process.env.NEXT_PUBLIC_API_BASE;
  return base ? base.replace(/\/+$/, "") : null;
}

/** Server-side read of a shared deck. The share endpoint is public, so this
 * does not send the API key. Returns null when the token is unknown. */
export async function fetchPublicDeck(token: string): Promise<PublicDeck | null> {
  if (!isShareToken(token)) return null;
  const base = apiBase() ?? "http://127.0.0.1:8000";
  try {
    const response = await fetch(`${base}/v1/decks/shared/${encodeURIComponent(token)}`, {
      cache: "no-store",
      signal: AbortSignal.timeout(8000)
    });
    if (!response.ok) return null;
    const body = (await response.json()) as Partial<PublicDeck>;
    if (!body || typeof body.name !== "string" || typeof body.share_token !== "string") return null;
    return asDeck(body as PublicDeck);
  } catch {
    return null;
  }
}

export type PublicDeckIndexRow = { share_token: string; updated_at: string };

/** Indexable decks for the sitemap. Skips the call when the API isn't
 * configured (local and CI builds) so a missing backend can't fail the build. */
export async function fetchPublicDeckIndex(): Promise<PublicDeckIndexRow[]> {
  const base = apiBase();
  if (!base) return [];
  const decks: PublicDeckIndexRow[] = [];
  try {
    for (let offset = 0; offset < 10_000; offset += 1000) {
      const response = await fetch(`${base}/v1/decks/public?limit=1000&offset=${offset}`, {
        next: { revalidate: 3600 },
        signal: AbortSignal.timeout(2500)
      });
      if (!response.ok) break;
      const body = (await response.json()) as { decks?: { share_token?: unknown; updated_at?: unknown }[] };
      const page = Array.isArray(body?.decks) ? body.decks : [];
      for (const row of page) {
        if (!row || typeof row.share_token !== "string" || !isShareToken(row.share_token)) continue;
        decks.push({
          share_token: row.share_token,
          updated_at: typeof row.updated_at === "string" ? row.updated_at : ""
        });
      }
      if (page.length < 1000) break;
    }
  } catch {
    return decks;
  }
  return decks;
}
