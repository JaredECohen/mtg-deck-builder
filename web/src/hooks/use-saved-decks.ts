"use client";

import { useCallback, useEffect, useState } from "react";

import { trackDeckShared } from "@/lib/analytics";
import { deleteSavedDeck, fetchDeckHistory, saveDeck, type DeckEvaluation, type SavedDeck } from "@/lib/api";
import type { DeckResponse } from "@/lib/types";

/** Share URL for a saved deck: opens it in the Analyze workflow. */
export function shareUrl(token: string): string {
  if (typeof window === "undefined") return `/?deck=${encodeURIComponent(token)}`;
  return `${window.location.origin}${window.location.pathname}?deck=${encodeURIComponent(token)}`;
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
    async (evaluation?: DeckEvaluation | null) => {
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
          evaluation: evaluation ?? undefined
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

/** The saved decks owned by this server's API key (GET /v1/decks/history). */
export function useSavedDeckList() {
  const [decks, setDecks] = useState<SavedDeck[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDecks(await fetchDeckHistory(20));
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

  return { decks, loading, error, load, remove };
}
