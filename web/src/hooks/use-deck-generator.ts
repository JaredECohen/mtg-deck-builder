"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { exportDeck as exportDeckApi, fetchMetaSummary, generateDeck, refineDeck } from "@/lib/api";
import type { ExportTarget, GenerateDeckInput } from "@/lib/api";
import type { DeckResponse, MetaSummaryResponse } from "@/lib/types";

const HISTORY_LIMIT = 5;

export function useDeckGenerator() {
  const [deck, setDeck] = useState<DeckResponse | null>(null);
  const [meta, setMeta] = useState<MetaSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // In-memory undo stack of prior deck states. Capped at HISTORY_LIMIT so
  // memory stays bounded. Cleared on fresh generate so a new build starts
  // with a clean slate. Not persisted.
  const [history, setHistory] = useState<DeckResponse[]>([]);

  const generateAbort = useRef<AbortController | null>(null);
  const refineAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      generateAbort.current?.abort();
      refineAbort.current?.abort();
    };
  }, []);

  const reset = useCallback(() => {
    setDeck(null);
    setMeta(null);
    setError(null);
    setHistory([]);
  }, []);

  // Push the current deck (if any) onto the history stack before a
  // destructive change (refine/apply). Keeps last HISTORY_LIMIT states.
  const pushHistory = useCallback((prev: DeckResponse | null) => {
    if (!prev) return;
    setHistory((h) => {
      const next = [...h, prev];
      if (next.length > HISTORY_LIMIT) next.shift();
      return next;
    });
  }, []);

  const generate = useCallback(async (input: GenerateDeckInput) => {
    generateAbort.current?.abort();
    const controller = new AbortController();
    generateAbort.current = controller;

    setLoading(true);
    setError(null);
    setHistory([]);  // fresh generation clears undo history
    try {
      const payload = await generateDeck(input, controller.signal);
      setDeck(payload);
      try {
        const metaPayload = await fetchMetaSummary(input.format, controller.signal);
        setMeta(metaPayload);
      } catch {
        /* meta is best-effort */
      }
      return payload;
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return null;
      setError(err instanceof Error ? err.message : "Unknown error");
      return null;
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  const refine = useCallback(async (prompt: string) => {
    if (!deck) return null;
    refineAbort.current?.abort();
    const controller = new AbortController();
    refineAbort.current = controller;

    setLoading(true);
    setError(null);
    pushHistory(deck);  // refine is destructive; preserve for undo
    try {
      const payload = await refineDeck(deck, prompt, controller.signal);
      setDeck(payload);
      return payload;
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return null;
      setError(err instanceof Error ? err.message : "Unknown error");
      return null;
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, [deck]);

  const exportDeck = useCallback(
    async (target: ExportTarget): Promise<string | null> => {
      if (!deck) return null;
      try {
        const payload = await exportDeckApi(deck, target);
        return payload.content;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Unknown error");
        return null;
      }
    },
    [deck]
  );

  const setDeckDirect = useCallback((next: DeckResponse) => {
    // Push the prior state before swapping (so "Apply sim-optimized" and
    // saved-deck loads are both undoable).
    setDeck((prev) => {
      if (prev) pushHistory(prev);
      return next;
    });
    setError(null);
  }, [pushHistory]);

  const undo = useCallback(() => {
    setHistory((h) => {
      if (h.length === 0) return h;
      const prev = h[h.length - 1];
      setDeck(prev);
      return h.slice(0, -1);
    });
  }, []);

  return { deck, meta, loading, error, history, setError, reset, generate, refine, exportDeck, setDeckDirect, undo };
}
