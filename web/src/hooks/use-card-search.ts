"use client";

import { useEffect, useState } from "react";

import { searchCards } from "@/lib/api";
import type { CardSearchResult, FormatName } from "@/lib/types";

export function useCardSearch(query: string, format: FormatName, enabled: boolean) {
  const [results, setResults] = useState<CardSearchResult[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled || query.trim().length < 2) {
      setResults([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(() => {
      setLoading(true);
      void searchCards(query, format, controller.signal)
        .then((payload) => {
          if (!controller.signal.aborted) setResults(payload.cards);
        })
        .catch(() => {
          /* best-effort search */
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 300);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, format, enabled]);

  return { results, loading };
}
