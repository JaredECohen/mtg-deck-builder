import type { CardRef, FormatName } from "@/lib/types";

export const MANUAL_DRAFT_STORAGE_KEY = "mtg-deck-builder-manual-draft";

export type ManualDraft = {
  format?: FormatName;
  mainboard?: CardRef[];
  sideboard?: CardRef[];
  commander?: string;
  notes?: string;
  refinePrompt?: string;
};

export function loadManualDraft(): ManualDraft | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(MANUAL_DRAFT_STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as ManualDraft;
  } catch {
    return null;
  }
}

export function saveManualDraft(draft: ManualDraft): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(MANUAL_DRAFT_STORAGE_KEY, JSON.stringify(draft));
  } catch {
    /* ignore quota errors */
  }
}

export function clearManualDraft(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(MANUAL_DRAFT_STORAGE_KEY);
}
