import catalog from "@/data/example-decks.json";

import type { ExampleCard } from "@/lib/example-decks";
import { readExampleDeck } from "@/lib/example-decks";

type Goldfish = { win_rate: number; avg_kill_turn: number | null; games: number };

export type CatalogDeck = {
  id: string;
  name: string;
  format: string;
  commander: string;
  source_url: string | null;
  mtgjson_file: string;
  mtgjson_deck_url: string;
  release_date: string;
  type: string;
  mainboard: ExampleCard[];
  sideboard: ExampleCard[];
  analysis: {
    total_cost_usd: number;
    top3_share: number | null;
    unpriced: string[];
    goldfish: Goldfish;
  };
};

type Catalog = {
  fetched_at?: string;
  decks?: object;
};

const data = catalog as Catalog;

export function catalogFetchedAt(): string {
  return typeof data.fetched_at === "string" ? data.fetched_at : "";
}

/** Full priced catalog for server-rendered deck blocks. Not imported by the builder. */
export function getCatalogDeck(id: string | null | undefined): CatalogDeck | null {
  const decks = data.decks;
  if (!decks || typeof decks !== "object") return null;
  const list = readExampleDeck(decks, id);
  if (!list || typeof id !== "string" || !Object.hasOwn(decks, id)) return null;
  const deck = (decks as Record<string, CatalogDeck>)[id];
  if (!deck.analysis || typeof deck.analysis.total_cost_usd !== "number" || !deck.analysis.goldfish) return null;
  if (typeof deck.type !== "string" || typeof deck.release_date !== "string") return null;
  return deck;
}
