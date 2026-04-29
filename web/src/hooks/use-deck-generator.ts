"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { exportDeck as exportDeckApi, fetchMetaSummary, generateDeck, refineDeck } from "@/lib/api";
import type { ExportTarget, GenerateDeckInput } from "@/lib/api";
import type { DeckResponse, MetaSummaryResponse } from "@/lib/types";

export function useDeckGenerator() {
  const [deck, setDeck] = useState<DeckResponse | null>(null);
  const [meta, setMeta] = useState<MetaSummaryResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
  }, []);

  const generate = useCallback(async (input: GenerateDeckInput) => {
    generateAbort.current?.abort();
    const controller = new AbortController();
    generateAbort.current = controller;

    setLoading(true);
    setError(null);
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

  return { deck, meta, loading, error, setError, reset, generate, refine, exportDeck };
}
