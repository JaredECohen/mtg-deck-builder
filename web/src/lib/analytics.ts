// Privacy-respecting funnel events for Vercel Web Analytics.
//
// Property values are closed enums or public guide slugs. Prompts, deck
// titles, card lists, emails, and share tokens are not accepted. Each event
// stays within two properties, which is the Pro plan limit. Hobby records
// page views only; custom events start appearing after a Pro upgrade.

export const ANALYTICS_EVENT_PROPS = {
  deck_generated: ["format", "source"],
  deck_refined: ["format"],
  deck_exported: ["target", "format"],
  deck_shared: ["format"],
  deck_page_viewed: ["format"],
  tcgplayer_cart_clicked: ["format"],
  guide_viewed: ["slug", "category"],
} as const;

export type AnalyticsEventName = keyof typeof ANALYTICS_EVENT_PROPS;

/** Formats the builder actually offers. Anything else is dropped. */
const FORMATS = new Set(["standard", "modern", "pioneer", "legacy", "commander"]);

/** Export targets in the funnel. Plain text and CSV are not part of it. */
const EXPORT_TARGETS = new Set(["arena", "moxfield", "archidekt"]);

const SOURCES = new Set(["new", "alternative"]);

// Keep in sync with CATEGORIES in blog.ts. analytics.test.ts checks that.
export const GUIDE_CATEGORIES = ["learn-to-play", "formats", "deck-archetypes", "strategy", "sets"] as const;

const GUIDE_CATEGORY_SET = new Set<string>(GUIDE_CATEGORIES);

// Public content ids only. Spaces, slashes, and punctuation cannot sneak a prompt in.
const SAFE_VALUE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const MAX_VALUE_LENGTH = 80;

// Query keys that may remain on a page-view URL. `brief` is the deck prompt
// and `deck` is the share token, so both are intentionally absent.
const QUERY_ALLOWLIST = new Set(["format", "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"]);
const MAX_QUERY_VALUE_LENGTH = 64;

export type AnalyticsProps = Record<string, string>;
export type AnalyticsTransport = (name: string, props: AnalyticsProps) => void;

export type SanitizedEvent = { name: AnalyticsEventName; props: AnalyticsProps };

function defaultTransport(name: string, props: AnalyticsProps) {
  // Loaded on demand so a blocked script, or a test that never sends, cannot
  // break deck building.
  void import("@vercel/analytics")
    .then(({ track }) => {
      try {
        track(name, props);
      } catch {
        // Analytics is best-effort.
      }
    })
    .catch(() => {
      // Analytics is best-effort.
    });
}

let transport: AnalyticsTransport = defaultTransport;

/** Swap the sender. Tests use this; production keeps the Vercel client. */
export function setAnalyticsTransport(next: AnalyticsTransport | null) {
  transport = next ?? defaultTransport;
}

function isSafeValue(value: unknown): value is string {
  return typeof value === "string" && value.length <= MAX_VALUE_LENGTH && SAFE_VALUE.test(value);
}

/**
 * Keep only the allowlisted properties for `name`. Returns null when a
 * required property is missing or not a safe value, so a prompt stuffed
 * into `format` is dropped with the event rather than forwarded.
 * Unknown keys (prompt, email, token, …) are ignored.
 */
export function sanitizeEvent(name: string, props: Record<string, unknown>): SanitizedEvent | null {
  const allowed = ANALYTICS_EVENT_PROPS[name as AnalyticsEventName];
  if (!allowed) return null;
  const clean: AnalyticsProps = {};
  for (const key of allowed) {
    const value = props[key];
    if (!isSafeValue(value)) return null;
    if (key === "format" && !FORMATS.has(value)) return null;
    if (key === "source" && !SOURCES.has(value)) return null;
    if (key === "target" && !EXPORT_TARGETS.has(value)) return null;
    if (key === "category" && !GUIDE_CATEGORY_SET.has(value)) return null;
    clean[key] = value;
  }
  return { name: name as AnalyticsEventName, props: clean };
}

function send(name: AnalyticsEventName, props: Record<string, unknown>) {
  const event = sanitizeEvent(name, props);
  if (!event) return;
  try {
    transport(event.name, event.props);
  } catch {
    // Analytics must never break the builder.
  }
}

export function trackDeckGenerated(format: string, source: "new" | "alternative") {
  send("deck_generated", { format, source });
}

export function trackDeckRefined(format: string) {
  send("deck_refined", { format });
}

export function trackDeckExported(target: string, format: string) {
  send("deck_exported", { target, format });
}

export function trackDeckShared(format: string) {
  send("deck_shared", { format });
}

/** A shared deck page was opened. Format only — the share token stays out of analytics. */
export function trackDeckPageViewed(format: string) {
  send("deck_page_viewed", { format });
}

export function trackTcgplayerCartClicked(format: string) {
  send("tcgplayer_cart_clicked", { format });
}

export function trackGuideViewed(slug: string, category: string) {
  send("guide_viewed", { slug, category });
}

function queryValueAllowed(key: string, value: string): boolean {
  if (!QUERY_ALLOWLIST.has(key)) return false;
  if (!value || value.length > MAX_QUERY_VALUE_LENGTH) return false;
  // Emails, sentences, and share-token-sized secrets do not belong in a campaign tag.
  if (/[\s@/]/.test(value)) return false;
  if (key === "format" && !FORMATS.has(value)) return false;
  return true;
}

/** Page URL with prompts and share tokens removed from the query string and from `/d/<token>`. Null if it cannot be parsed. */
export function redactAnalyticsUrl(raw: string): string | null {
  let url: URL;
  try {
    url = new URL(raw, "https://mtgdecklab.app");
  } catch {
    return null;
  }
  for (const key of [...url.searchParams.keys()]) {
    const value = url.searchParams.get(key) ?? "";
    if (!queryValueAllowed(key, value)) url.searchParams.delete(key);
  }
  // The share token is the path on /d/<token>, not a query param.
  if (url.pathname === "/d/" || url.pathname.startsWith("/d/")) url.pathname = "/d";
  const absolute = /^https?:\/\//i.test(raw);
  if (!absolute) return `${url.pathname}${url.search}${url.hash}`;
  return url.toString();
}

/** `beforeSend` filter: strip sensitive query params from the page URL. */
export function redactAnalyticsEvent<T extends { url: string }>(event: T): T | null {
  const url = redactAnalyticsUrl(event.url);
  if (url === null) return null;
  if (url === event.url) return event;
  return { ...event, url };
}
