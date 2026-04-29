"use client";

import { useEffect, useState } from "react";

import { fetchCommanderProfile, searchCommanders } from "@/lib/api";
import type { CommanderProfile, CommanderSearchResult, FormatName } from "@/lib/types";

export type CommanderSort = "match" | "popularity" | "support" | "name";

export type CommanderSearchInput = {
  format: FormatName;
  colors: string[];
  playstyleTags: string[];
  themeTags: string[];
  search: string;
  sort: CommanderSort;
  enabled: boolean;
};

export function useCommanderSearch(input: CommanderSearchInput) {
  const [commanders, setCommanders] = useState<CommanderSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!input.enabled) {
      setCommanders([]);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    void searchCommanders(
      {
        colors: input.colors,
        playstyle_tags: input.playstyleTags,
        theme_tags: input.themeTags,
        search: input.search,
        sort: input.sort,
        limit: 18
      },
      controller.signal
    )
      .then((payload) => {
        if (!controller.signal.aborted) setCommanders(payload.commanders);
      })
      .catch((err: unknown) => {
        if (err instanceof Error && err.name === "AbortError") return;
        setError("Could not load commanders — check your connection.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [input.colors.join(","), input.search, input.sort, input.format, input.playstyleTags.join(","), input.themeTags.join(","), input.enabled]);

  return { commanders, loading, error };
}

export function useCommanderProfile(commanderName: string, enabled: boolean) {
  const [profile, setProfile] = useState<CommanderProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !commanderName) {
      setProfile(null);
      return;
    }
    const controller = new AbortController();
    void fetchCommanderProfile(commanderName, controller.signal)
      .then((payload) => {
        if (!controller.signal.aborted) setProfile(payload.commander);
      })
      .catch((err: unknown) => {
        if (err instanceof Error && err.name === "AbortError") return;
        setProfile(null);
        setError("Could not load commander profile — check your connection.");
      });
    return () => controller.abort();
  }, [commanderName, enabled]);

  return { profile, error };
}
