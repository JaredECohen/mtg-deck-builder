"use client";

import { useCallback, useState } from "react";

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

  const analyze = useCallback(async (payload: AnalyzePayload) => {
    if (!payload.mainboard.length) {
      setError("Add at least one card to your deck before analyzing.");
      return null;
    }
    setLoading(true);
    setError(null);
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
    setLoading(true);
    setError(null);
    try {
      const payload = await parseDeckText(format, text);
      if (payload.warnings.length) setError(payload.warnings.join(" "));
      return payload;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const reset = useCallback(() => {
    setAnalysis(null);
    setError(null);
  }, []);

  return { analysis, loading, error, setError, analyze, importText, reset };
}
