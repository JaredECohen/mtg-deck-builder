import catalog from "@/data/example-deck-lists.json";
import type { ManualDraft } from "@/lib/manual-draft";
import type { FormatName } from "@/lib/types";

export type ExampleCard = { name: string; quantity: number };

export type ExampleDeck = {
  id: string;
  name: string;
  format: FormatName;
  commander: string;
  mainboard: ExampleCard[];
  sideboard: ExampleCard[];
};

const FORMATS = new Set<FormatName>(["standard", "modern", "pioneer", "legacy", "commander"]);

type Catalog = {
  fetched_at?: string;
  decks?: object;
};

const data = catalog as Catalog;

function isCardList(value: unknown): value is ExampleCard[] {
  if (!Array.isArray(value)) return false;
  return value.every((card) => {
    if (!card || typeof card !== "object") return false;
    const record = card as ExampleCard;
    return typeof record.name === "string" && record.name.length > 0 && typeof record.quantity === "number" && record.quantity > 0;
  });
}

/** Own-property lookup. `decks[id]` would also see Object.prototype keys. */
export function readExampleDeck(decks: object, id: string | null | undefined): ExampleDeck | null {
  if (typeof id !== "string" || id.length === 0) return null;
  if (!Object.hasOwn(decks, id)) return null;
  const deck = (decks as Record<string, unknown>)[id];
  if (!deck || typeof deck !== "object") return null;
  const record = deck as ExampleDeck;
  if (typeof record.name !== "string" || record.name.length === 0) return null;
  if (!FORMATS.has(record.format)) return null;
  if (typeof record.commander !== "string") return null;
  if (!isCardList(record.mainboard) || !isCardList(record.sideboard)) return null;
  return record;
}

export function listExampleDeckIds(): string[] {
  const decks = data.decks;
  if (!decks || typeof decks !== "object") return [];
  return Object.keys(decks).filter((id) => readExampleDeck(decks, id) !== null);
}

export function getExampleDeck(id: string | null | undefined): ExampleDeck | null {
  const decks = data.decks;
  if (!decks || typeof decks !== "object") return null;
  return readExampleDeck(decks, id);
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

export type AnalyzeSeed = {
  format: FormatName | null;
  mainboard: ExampleCard[];
  sideboard: ExampleCard[];
  commander: string;
  notes: string;
  /** False when the editor was filled from ?example=, so autosave must leave the saved draft alone. */
  persistDraft: boolean;
};

/**
 * An official example fills the editor and must not be replaced by the saved
 * draft, and must not be written back over that draft.
 */
export function resolveAnalyzeSeed(options: {
  example: ReturnType<typeof prepopulateFromExample>;
  draft: ManualDraft | null;
  defaultNotes: string;
}): AnalyzeSeed {
  if (options.example) {
    return {
      format: options.example.format,
      mainboard: options.example.mainboard,
      sideboard: options.example.sideboard,
      commander: options.example.commander,
      notes: `Official list loaded: ${options.example.name}`,
      persistDraft: false,
    };
  }
  const draft = options.draft;
  return {
    format: draft?.format ?? null,
    mainboard: draft?.mainboard ?? [],
    sideboard: draft?.sideboard ?? [],
    commander: draft?.commander ?? "",
    notes: draft?.notes ? draft.notes : options.defaultNotes,
    persistDraft: true,
  };
}
