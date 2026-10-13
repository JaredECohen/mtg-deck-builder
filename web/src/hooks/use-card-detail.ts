"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { fetchCardDetail, fetchSimilarCards } from "@/lib/api";
import type { CardRecord, FormatName } from "@/lib/types";

/** Where the card was opened from: drives the "similar cards you could play" filter. */
export type CardContext = {
  format?: FormatName;
  /** Deck colors. Similar cards are limited to these (colorless always allowed). */
  colors?: string[];
};

export type SimilarCard = { name: string; score: number };

/**
 * Card-detail modal state. The modal opens immediately on `open(name)` with a
 * loading state; a newer `open` aborts the previous fetch, and closing returns
 * focus to the element that opened the modal.
 */
export function useCardDetail() {
  const [name, setName] = useState<string | null>(null);
  const [card, setCard] = useState<CardRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [context, setContext] = useState<CardContext>({});
  const [similar, setSimilar] = useState<SimilarCard[] | null>(null);
  const [similarLoading, setSimilarLoading] = useState(false);
  const [similarError, setSimilarError] = useState<string | null>(null);

  const abort = useRef<AbortController | null>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const open = useCallback(async (cardName: string, nextContext: CardContext = {}) => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;

    // Remember the trigger only when the modal is not already open (clicking a
    // similar card inside the modal keeps the original trigger).
    if (typeof document !== "undefined" && !document.querySelector(".card-modal")) {
      const active = document.activeElement;
      returnFocus.current = active instanceof HTMLElement ? active : null;
    }

    setName(cardName);
    setContext(nextContext);
    setCard(null);
    setError(null);
    setLoading(true);
    setSimilar(null);
    setSimilarError(null);
    setSimilarLoading(true);

    const detail = fetchCardDetail(cardName, controller.signal)
      .then((payload) => {
        if (controller.signal.aborted) return;
        setCard(payload.card);
        if (!payload.card.image_uri && !payload.card.faces.some((face) => face.image_uri)) {
          setError("No card image was available for this card.");
        }
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setError(err instanceof Error ? err.message : "Could not load card details.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    const alternatives = fetchSimilarCards(
      cardName,
      { k: 6, format: nextContext.format, colors: nextContext.colors },
      controller.signal
    )
      .then((payload) => {
        if (controller.signal.aborted) return;
        setSimilar(payload.similar.filter((entry) => entry.name !== cardName));
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setSimilarError(err instanceof Error ? err.message : "Similar-card lookup failed");
      })
      .finally(() => {
        if (!controller.signal.aborted) setSimilarLoading(false);
      });

    await Promise.all([detail, alternatives]);
  }, []);

  const close = useCallback(() => {
    abort.current?.abort();
    setName(null);
    setCard(null);
    setError(null);
    setLoading(false);
    setSimilar(null);
    setSimilarLoading(false);
    setSimilarError(null);
    const target = returnFocus.current;
    returnFocus.current = null;
    // After React removes the dialog, put focus back where the user was.
    if (target) setTimeout(() => target.isConnected && target.focus(), 0);
  }, []);

  useEffect(() => {
    if (!name) return;
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") close();
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [name, close]);

  return {
    isOpen: name !== null,
    name,
    card,
    loading,
    error,
    context,
    similar,
    similarLoading,
    similarError,
    open,
    close
  };
}

export type CardDetailState = ReturnType<typeof useCardDetail>;
