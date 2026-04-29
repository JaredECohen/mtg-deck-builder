"use client";

import { useCallback, useEffect, useState } from "react";

import { fetchCardDetail } from "@/lib/api";
import type { CardRecord } from "@/lib/types";

export function useCardDetail() {
  const [card, setCard] = useState<CardRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const open = useCallback(async (name: string) => {
    setLoading(true);
    setError(null);
    try {
      const payload = await fetchCardDetail(name);
      if (!payload.card.image_uri && !payload.card.faces.some((face) => face.image_uri)) {
        setError("No card image was available for this card.");
      }
      setCard(payload.card);
    } catch (fetchError) {
      setError(fetchError instanceof Error ? fetchError.message : "Could not load card details.");
      setCard({
        oracle_id: null,
        scryfall_id: null,
        name,
        normalized_name: null,
        mana_cost: "",
        mana_value: 0,
        colors: [],
        color_identity: [],
        type_line: "",
        oracle_text: "",
        keywords: [],
        layout: null,
        rarity: null,
        set_code: null,
        released_at: null,
        image_uri: null,
        image_uris: {},
        faces: [],
        price_usd: null,
        price_usd_foil: null,
        legalities: {},
        tags: [],
        purchase_links: {}
      });
    } finally {
      setLoading(false);
    }
  }, []);

  const close = useCallback(() => {
    setCard(null);
    setError(null);
  }, []);

  useEffect(() => {
    if (!card) return;
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") close();
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [card, close]);

  return { card, loading, error, open, close };
}
