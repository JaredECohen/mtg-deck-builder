"use client";

import { useCallback, useRef, useState } from "react";

import { evaluateDeck, type CardRefInput, type DeckEvaluation } from "@/lib/api";
import type { FormatName } from "@/lib/types";

export function useDeckEvaluation() {
  const [evaluation, setEvaluation] = useState<DeckEvaluation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abort.current?.abort();
    setEvaluation(null);
    setError(null);
    setLoading(false);
  }, []);

  const evaluate = useCallback(async (format: FormatName, mainboard: CardRefInput[]) => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setLoading(true);
    setError(null);
    try {
      const result = await evaluateDeck({ format, mainboard, games: 200 }, controller.signal);
      setEvaluation(result);
      return result;
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return null;
      setError(err instanceof Error ? err.message : "Evaluation failed");
      return null;
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  return { evaluation, loading, error, evaluate, reset };
}
