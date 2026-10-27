"use client";

import { useCallback, useEffect, useState } from "react";

import { trackDeckShared } from "@/lib/analytics";
import {
  deleteSavedDeck,
  fetchDeckHistory,
  saveDeck,
  type DeckEvaluation,
  type DeckVisibility,
  type SavedDeck
} from "@/lib/api";
import type { DeckResponse } from "@/lib/types";

const LOCAL_KEY = "decklab.local-decks";

export type LocalDeck = {
  id: string;
  share_token: string;
  name: string;
  format: string;
  created_at: string;
  visibility: DeckVisibility;
};

/** Public page for a shared deck. */
export function shareUrl(token: string): string {
  const path = `/d/${encodeURIComponent(token)}`;
  if (typeof window === "undefined") return path;
  return `${window.location.origin}${path}`;
}

/** Opens the same list in the Analyze workflow. */
export function analyzeUrl(token: string): string {
  return `/?deck=${encodeURIComponent(token)}`;
}

function keyCardsFor(deck: DeckResponse): string[] {
  const lands = new Set(
    Object.entries(deck.card_types)
      .filter(([, type]) => type === "Land")
      .map(([name]) => name)
  );
  const fromRoles = [...new Set(deck.role_summary.flatMap((role) => role.key_cards))].filter((name) => !lands.has(name));
  if (fromRoles.length) return fromRoles.slice(0, 4);
  return deck.mainboard
    .map((card) => card.name)
    .filter((name) => !lands.has(name))
    .slice(0, 4);
}

/** Save the deck on screen and mint a share link. Resets when the deck changes. */
export function useSaveDeck(deck: DeckResponse | null) {
  const [saved, setSaved] = useState<SavedDeck | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSaved(null);
    setError(null);
    setSaving(false);
  }, [deck]);

  const save = useCallback(
    async (evaluation?: DeckEvaluation | null, visibility: DeckVisibility = "public") => {
      if (!deck) return null;
      const target = deck;
      setSaving(true);
      setError(null);
      try {
        const result = await saveDeck({
          name: target.title,
          format: target.format,
          mainboard: target.mainboard,
          sideboard: target.sideboard,
          commander: target.commander ?? undefined,
          notes: target.strategy_summary,
          evaluation: evaluation ?? undefined,
          visibility,
          colors: target.colors,
          price_usd: target.estimated_price_usd ?? null,
          card_notes: target.card_notes.slice(0, 250).map((note) => ({
            name: note.name,
            role: note.role.slice(0, 80),
            reason: note.reason.slice(0, 2000)
          })),
          mana_curve: target.mana_curve,
          card_types: target.card_types,
          key_cards: keyCardsFor(target)
        });
        setSaved(result);
        trackDeckShared(result.format);
        return result;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Saving deck failed");
        return null;
      } finally {
        setSaving(false);
      }
    },
    [deck]
  );

  return { saved, saving, error, save };
}

export function readLocalDecks(): LocalDeck[] {
  if (typeof window === "undefined") return [];
  try {
    const parsed = JSON.parse(window.localStorage.getItem(LOCAL_KEY) ?? "[]") as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((row): row is LocalDeck => Boolean(row && typeof row.id === "string" && typeof row.share_token === "string")).slice(0, 30);
  } catch {
    return [];
  }
}

export function rememberLocalDeck(deck: SavedDeck): LocalDeck[] {
  const entry: LocalDeck = {
    id: deck.id,
    share_token: deck.share_token,
    name: deck.name,
    format: deck.format,
    created_at: deck.created_at,
    visibility: deck.visibility === "unlisted" ? "unlisted" : "public"
  };
  const next = [entry, ...readLocalDecks().filter((row) => row.id !== deck.id)].slice(0, 30);
  window.localStorage.setItem(LOCAL_KEY, JSON.stringify(next));
  return next;
}

export function forgetLocalDeck(id: string): LocalDeck[] {
  const next = readLocalDecks().filter((row) => row.id !== id);
  window.localStorage.setItem(LOCAL_KEY, JSON.stringify(next));
  return next;
}

/** The signed-in library (GET /v1/decks/history, scoped to the session). */
export function useSavedDeckList() {
  const [decks, setDecks] = useState<SavedDeck[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDecks(await fetchDeckHistory(50));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load saved decks");
    } finally {
      setLoading(false);
    }
  }, []);

  const remove = useCallback(async (id: string) => {
    setError(null);
    try {
      await deleteSavedDeck(id);
      setDecks((list) => (list ? list.filter((deck) => deck.id !== id) : list));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete the saved deck");
    }
  }, []);

  return { decks, loading, error, load, remove, setDecks };
}
