"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { fetchMetaSummary, generateDeck, refineDeck } from "@/lib/api";
import type { GenerateDeckInput } from "@/lib/api";
import type { DeckResponse, MetaSummaryResponse } from "@/lib/types";

// Revisions kept in memory (oldest first; the last one is the deck on screen).
const REVISION_LIMIT = 10;

export type RevisionKind = "generate" | "refine" | "optimize" | "restore";

export type DeckRevision = {
  id: number;
  deck: DeckResponse;
  kind: RevisionKind;
  label: string;
  createdAt: number;
};

export type GeneratorAction = "generate" | "refine";

let revisionSeq = 0;

function makeRevision(deck: DeckResponse, kind: RevisionKind, label: string): DeckRevision {
  revisionSeq += 1;
  return { id: revisionSeq, deck, kind, label, createdAt: Date.now() };
}

function appendRevision(list: DeckRevision[], next: DeckRevision): DeckRevision[] {
  const out = [...list, next];
  // Drop the oldest; the current (last) revision always stays.
  while (out.length > REVISION_LIMIT) out.shift();
  return out;
}

export function useDeckGenerator() {
  const [revisions, setRevisions] = useState<DeckRevision[]>([]);
  const [meta, setMeta] = useState<MetaSummaryResponse | null>(null);
  const [metaError, setMetaError] = useState<string | null>(null);
  const [action, setAction] = useState<GeneratorAction | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The request behind the current deck, so "Build this" alternatives and the
  // "built for another format" check reuse the exact same constraints.
  const [lastInput, setLastInput] = useState<GenerateDeckInput | null>(null);

  const generateAbort = useRef<AbortController | null>(null);
  const refineAbort = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      generateAbort.current?.abort();
      refineAbort.current?.abort();
    };
  }, []);

  const current = revisions.length ? revisions[revisions.length - 1] : null;
  const deck = current?.deck ?? null;

  const reset = useCallback(() => {
    generateAbort.current?.abort();
    refineAbort.current?.abort();
    setRevisions([]);
    setMeta(null);
    setMetaError(null);
    setError(null);
    setAction(null);
    setLastInput(null);
  }, []);

  const generate = useCallback(async (input: GenerateDeckInput) => {
    generateAbort.current?.abort();
    refineAbort.current?.abort();
    const controller = new AbortController();
    generateAbort.current = controller;

    setAction("generate");
    setError(null);
    // The snapshot belongs to the previous format until the new one arrives.
    setMeta(null);
    setMetaError(null);
    try {
      const payload = await generateDeck(input, controller.signal);
      if (controller.signal.aborted) return null;
      // A fresh build starts a fresh revision history.
      setRevisions([makeRevision(payload, "generate", input.archetype_name ? `Built "${input.archetype_name}"` : "Generated")]);
      setLastInput(input);
      try {
        const metaPayload = await fetchMetaSummary(payload.format, controller.signal);
        if (!controller.signal.aborted) setMeta(metaPayload);
      } catch (metaErr) {
        if (!controller.signal.aborted) {
          setMetaError(metaErr instanceof Error ? metaErr.message : "Meta snapshot unavailable");
        }
      }
      return payload;
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return null;
      setError(err instanceof Error ? err.message : "Unknown error");
      return null;
    } finally {
      if (!controller.signal.aborted) setAction(null);
    }
  }, []);

  const refine = useCallback(
    async (prompt: string) => {
      if (!deck) return null;
      refineAbort.current?.abort();
      const controller = new AbortController();
      refineAbort.current = controller;

      setAction("refine");
      setError(null);
      try {
        const payload = await refineDeck(deck, prompt, controller.signal);
        if (controller.signal.aborted) return null;
        // Only a successful refine becomes a revision; a failure leaves the
        // history untouched so it can simply be retried.
        const label = prompt.trim().length > 60 ? `${prompt.trim().slice(0, 57)}…` : prompt.trim();
        setRevisions((list) => appendRevision(list, makeRevision(payload, "refine", `Refined: ${label || "refinement"}`)));
        return payload;
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") return null;
        setError(err instanceof Error ? err.message : "Unknown error");
        return null;
      } finally {
        if (!controller.signal.aborted) setAction(null);
      }
    },
    [deck]
  );

  /** Replace the deck on screen (e.g. the sim-optimized version); undoable. */
  const applyDeck = useCallback((next: DeckResponse, label: string, kind: RevisionKind = "optimize") => {
    setRevisions((list) => appendRevision(list, makeRevision(next, kind, label)));
    setError(null);
  }, []);

  const undo = useCallback(() => {
    setRevisions((list) => (list.length > 1 ? list.slice(0, -1) : list));
  }, []);

  /** Make an earlier revision current again by appending a copy (so restoring is undoable too). */
  const restore = useCallback((id: number) => {
    setRevisions((list) => {
      const target = list.find((revision) => revision.id === id);
      if (!target || target === list[list.length - 1]) return list;
      return appendRevision(list, makeRevision(target.deck, "restore", `Restored: ${target.label}`));
    });
  }, []);

  return {
    deck,
    current,
    revisions,
    meta,
    metaError,
    loading: action !== null,
    action,
    error,
    lastInput,
    setError,
    reset,
    generate,
    refine,
    applyDeck,
    undo,
    restore
  };
}
