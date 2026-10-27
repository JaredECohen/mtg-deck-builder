"use client";

import { Analytics, type BeforeSendEvent } from "@vercel/analytics/next";

import { redactAnalyticsEvent } from "@/lib/analytics";

/** Cookieless Vercel Web Analytics. Prompts and share tokens are removed from the page URL first. */
export function SiteAnalytics() {
  return <Analytics beforeSend={(event: BeforeSendEvent) => redactAnalyticsEvent(event)} />;
}
