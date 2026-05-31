"use client";

import { useCallback, useEffect, useState } from "react";

import { deleteSavedDeck, listSavedDecks, loadSavedDeck, saveDeck } from "@/lib/api";
import type { ChatTurn, SavedDeckSummary } from "@/lib/api";
import type { DeckResponse } from "@/lib/types";

const STORAGE_KEY = "mtg-deck-lab-session-id";

function ensureSessionId(): string {
  if (typeof window === "undefined") return "";
  let id = window.localStorage.getItem(STORAGE_KEY);
  if (!id) {
    id = `s-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
    window.localStorage.setItem(STORAGE_KEY, id);
  }
  return id;
}

export function useSavedDecks() {
  const [sessionId, setSessionId] = useState("");
  const [decks, setDecks] = useState<SavedDeckSummary[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSessionId(ensureSessionId());
  }, []);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    try {
      const payload = await listSavedDecks(sessionId);
      setDecks(payload);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load saved decks");
    }
  }, [sessionId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const save = useCallback(
    async (deck: DeckResponse, chatHistory: ChatTurn[] = []) => {
      if (!sessionId) return null;
      setSaving(true);
      try {
        const summary = await saveDeck(sessionId, deck, chatHistory);
        await refresh();
        return summary;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Save failed");
        return null;
      } finally {
        setSaving(false);
      }
    },
    [sessionId, refresh]
  );

  const remove = useCallback(
    async (deckId: string) => {
      if (!sessionId) return;
      try {
        await deleteSavedDeck(deckId, sessionId);
        await refresh();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Delete failed");
      }
    },
    [sessionId, refresh]
  );

  const load = useCallback(async (deckId: string): Promise<{ deck: DeckResponse; chatHistory: ChatTurn[] } | null> => {
    try {
      const detail = await loadSavedDeck(deckId);
      return { deck: detail.deck, chatHistory: detail.chat_history ?? [] };
    } catch (err) {
      setError(err instanceof Error ? err.message : "Load failed");
      return null;
    }
  }, []);

  return { sessionId, decks, saving, error, save, remove, load, refresh };
}
