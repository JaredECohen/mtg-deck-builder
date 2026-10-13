"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { exportDeck, type ExportTarget } from "@/lib/api";
import type { DeckResponse } from "@/lib/types";

/**
 * Export text for the deck on screen. A deck change (refine, undo, new
 * generation) aborts any in-flight export and clears the old text, so a slow
 * response can never show a previous list.
 */
export function useDeckExport(deck: DeckResponse | null) {
  const [content, setContent] = useState("");
  const [target, setTarget] = useState<ExportTarget | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    abort.current?.abort();
    setContent("");
    setTarget(null);
    setError(null);
    setLoading(false);
  }, [deck]);

  useEffect(() => () => abort.current?.abort(), []);

  const run = useCallback(
    async (nextTarget: ExportTarget) => {
      if (!deck) return null;
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      setLoading(true);
      setError(null);
      try {
        const payload = await exportDeck(deck, nextTarget, controller.signal);
        if (controller.signal.aborted) return null;
        setContent(payload.content);
        setTarget(nextTarget);
        return payload.content;
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return null;
        setError(err instanceof Error ? err.message : "Export failed");
        return null;
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [deck]
  );

  return { content, target, loading, error, run };
}
