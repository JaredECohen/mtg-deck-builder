// Google AdSense configuration, inlined at build time. Nothing ad-related
// renders, loads, or is served (including /ads.txt) until
// NEXT_PUBLIC_ADSENSE_CLIENT is set to the publisher ID from the AdSense
// dashboard, e.g. ca-pub-1234567890123456. A malformed value is ignored
// rather than injected into the script URL.

/** Publisher id from the AdSense dashboard, `ca-pub-` plus 10 to 20 digits. */
export const PUBLISHER_ID_PATTERN = /^ca-pub-\d{10,20}$/;

export function publisherId(value: string | null | undefined): string {
  const raw = value ?? "";
  return PUBLISHER_ID_PATTERN.test(raw) ? raw : "";
}

const RAW_CLIENT = process.env.NEXT_PUBLIC_ADSENSE_CLIENT ?? "";

export const ADSENSE_CLIENT = publisherId(RAW_CLIENT);

// Optional manual ad unit for the page footer. Without it, ads appear only
// where Auto ads (configured in the AdSense dashboard) places them.
export const ADSENSE_FOOTER_SLOT = /^\d{6,20}$/.test(process.env.NEXT_PUBLIC_ADSENSE_SLOT_FOOTER ?? "")
  ? (process.env.NEXT_PUBLIC_ADSENSE_SLOT_FOOTER as string)
  : "";

// Optional manual unit placed inside guide articles (<InArticleAd /> in MDX).
export const ADSENSE_IN_ARTICLE_SLOT = /^\d{6,20}$/.test(process.env.NEXT_PUBLIC_ADSENSE_SLOT_IN_ARTICLE ?? "")
  ? (process.env.NEXT_PUBLIC_ADSENSE_SLOT_IN_ARTICLE as string)
  : "";

/** A manual unit renders only when this page allows ads and both ids are set. */
export function shouldRenderAdSlot(options: { allowed: boolean; client?: string; slot?: string }): boolean {
  return options.allowed && Boolean(options.client) && Boolean(options.slot);
}

// ads.txt line authorizing Google to sell this site's inventory. The
// certification authority ID f08c47fec0942fa0 is Google's, the same for
// every publisher. Pass the client id; a missing or malformed id returns null
// so the route can 404 instead of publishing a placeholder file.
export function adsTxt(client: string | null | undefined = process.env.NEXT_PUBLIC_ADSENSE_CLIENT): string | null {
  const id = publisherId(client);
  if (!id) return null;
  return `google.com, ${id.replace(/^ca-/, "")}, DIRECT, f08c47fec0942fa0`;
}
