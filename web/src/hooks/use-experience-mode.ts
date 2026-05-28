"use client";

/**
 * Beginner vs. expert mode, persisted to localStorage.
 *
 * Beginner mode hides dense simulator internals (metric grids, raw
 * fitness vectors); expert mode surfaces everything. Components read
 * `detailed` to decide how much to show.
 */

import { useCallback, useEffect, useState } from "react";

export type ExperienceMode = "beginner" | "expert";

const STORAGE_KEY = "mtg.experienceMode";

export function useExperienceMode(): {
  mode: ExperienceMode;
  detailed: boolean;
  setMode: (mode: ExperienceMode) => void;
  toggle: () => void;
} {
  const [mode, setModeState] = useState<ExperienceMode>("beginner");

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "beginner" || stored === "expert") {
        setModeState(stored);
      }
    } catch {
      /* localStorage unavailable (SSR / privacy mode) — keep default */
    }
  }, []);

  const setMode = useCallback((next: ExperienceMode) => {
    setModeState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* ignore persistence failures */
    }
  }, []);

  const toggle = useCallback(() => {
    setMode(mode === "beginner" ? "expert" : "beginner");
  }, [mode, setMode]);

  return { mode, detailed: mode === "expert", setMode, toggle };
}
