"use client";

import { Analytics, type BeforeSendEvent } from "@vercel/analytics/next";

import { redactAnalyticsEvent } from "@/lib/analytics";

/** Cookieless Vercel Web Analytics. Query strings that carry prompts or share tokens are removed first. */
export function SiteAnalytics() {
  return <Analytics beforeSend={(event: BeforeSendEvent) => redactAnalyticsEvent(event)} />;
}
