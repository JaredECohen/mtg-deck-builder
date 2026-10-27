"use client";

import { useEffect } from "react";

import { trackDeckPageViewed } from "@/lib/analytics";

/** Records one deck_page_viewed event. Only the format is sent; the share token is not. */
export function DeckPageView({ format }: { format: string }) {
  useEffect(() => {
    trackDeckPageViewed(format);
  }, [format]);
  return null;
}
