import catalog from "@/data/example-decks.json";
import type { FormatName } from "@/lib/types";

export type ExampleCard = { name: string; quantity: number };

export type ExampleDeck = {
  id: string;
  name: string;
  format: FormatName;
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
    goldfish: { win_rate: number; avg_kill_turn: number | null; games: number };
  };
};

type Catalog = {
  fetched_at: string;
  decks: Record<string, ExampleDeck>;
};

const data = catalog as Catalog;

export function listExampleDeckIds(): string[] {
  return Object.keys(data.decks);
}

export function getExampleDeck(id: string | null | undefined): ExampleDeck | null {
  if (!id) return null;
  return data.decks[id] ?? null;
}

/** Opens the deck builder with this official list filled in. */
export function exampleBuilderHref(id: string): string {
  return `/?example=${encodeURIComponent(id)}#builder`;
}

export function prepopulateFromExample(id: string | null | undefined): {
  format: FormatName;
  mainboard: ExampleCard[];
  sideboard: ExampleCard[];
  commander: string;
  name: string;
} | null {
  const deck = getExampleDeck(id);
  if (!deck) return null;
  return {
    format: deck.format,
    mainboard: deck.mainboard.map((card) => ({ name: card.name, quantity: card.quantity })),
    sideboard: deck.sideboard.map((card) => ({ name: card.name, quantity: card.quantity })),
    commander: deck.commander,
    name: deck.name,
  };
}
