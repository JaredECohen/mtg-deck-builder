import type { CardRef, FormatName } from "@/lib/types";

export const MANUAL_DRAFT_STORAGE_KEY = "mtg-deck-builder-manual-draft";

export type ManualDraft = {
  format?: FormatName;
  mainboard?: CardRef[];
  sideboard?: CardRef[];
  commander?: string;
  notes?: string;
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
  try {
    window.localStorage.removeItem(MANUAL_DRAFT_STORAGE_KEY);
  } catch {
    /* storage unavailable (privacy mode, blocked site data) */
  }
}

// The Generate workflow's Refine box. Kept under its own key so the Analyze
// workflow's draft autosave never overwrites it.
export const REFINE_DRAFT_STORAGE_KEY = "mtg-deck-builder-refine-draft";

export function loadRefineDraft(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(REFINE_DRAFT_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function saveRefineDraft(value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(REFINE_DRAFT_STORAGE_KEY, value);
  } catch {
    /* ignore quota errors */
  }
}
