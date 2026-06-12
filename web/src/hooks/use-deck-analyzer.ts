"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { analyzeDeck, parseDeckText } from "@/lib/api";
import type { CardRef, DeckAnalysisResponse, FormatName, ParsedDecklistResponse } from "@/lib/types";

export type AnalyzePayload = {
  format: FormatName;
  commander?: string;
  mainboard: CardRef[];
  sideboard: CardRef[];
  notes: string;
  deep_analysis?: boolean;
};

export function useDeckAnalyzer() {
  const [analysis, setAnalysis] = useState<DeckAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Non-fatal parse warnings (e.g. unrecognized lines on import). Kept
  // separate from `error` so the UI can style them as cautions, not failures.
  const [warnings, setWarnings] = useState<string[]>([]);

  const importAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      importAbort.current?.abort();
    };
  }, []);

  const analyze = useCallback(async (payload: AnalyzePayload) => {
    if (!payload.mainboard.length) {
      setError("Add at least one card to your deck before analyzing.");
      return null;
    }
    setLoading(true);
    setError(null);
    setWarnings([]);
    try {
      const result = await analyzeDeck(payload);
      setAnalysis(result);
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const importText = useCallback(async (format: FormatName, text: string): Promise<ParsedDecklistResponse | null> => {
    if (!text.trim()) {
      setError("Paste a deck list before importing.");
      return null;
    }
    importAbort.current?.abort();
    const controller = new AbortController();
    importAbort.current = controller;

    setLoading(true);
    setError(null);
    setWarnings([]);
    try {
      const payload = await parseDeckText(format, text, controller.signal);
      setWarnings(payload.warnings);
      return payload;
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return null;
      setError(err instanceof Error ? err.message : "Unknown error");
      return null;
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  const reset = useCallback(() => {
    setAnalysis(null);
    setError(null);
    setWarnings([]);
  }, []);

  return { analysis, loading, error, warnings, setError, analyze, importText, reset };
}
