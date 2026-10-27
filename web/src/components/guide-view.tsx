"use client";

import { useEffect } from "react";

import { trackGuideViewed } from "@/lib/analytics";

/** Records one guide_viewed event for this article. The slug and category are public content ids. */
export function GuideView({ slug, category }: { slug: string; category: string }) {
  useEffect(() => {
    trackGuideViewed(slug, category);
  }, [slug, category]);
  return null;
}
