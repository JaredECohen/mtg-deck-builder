// Google AdSense configuration, inlined at build time. Nothing ad-related
// renders, loads, or is served (including /ads.txt) until
// NEXT_PUBLIC_ADSENSE_CLIENT is set to the publisher ID from the AdSense
// dashboard, e.g. ca-pub-1234567890123456. A malformed value is ignored
// rather than injected into the script URL.

const RAW_CLIENT = process.env.NEXT_PUBLIC_ADSENSE_CLIENT ?? "";

export const ADSENSE_CLIENT = /^ca-pub-\d{10,20}$/.test(RAW_CLIENT) ? RAW_CLIENT : "";

// Optional manual ad unit for the page footer. Without it, ads appear only
// where Auto ads (configured in the AdSense dashboard) places them.
export const ADSENSE_FOOTER_SLOT = /^\d{6,20}$/.test(process.env.NEXT_PUBLIC_ADSENSE_SLOT_FOOTER ?? "")
  ? (process.env.NEXT_PUBLIC_ADSENSE_SLOT_FOOTER as string)
  : "";

// Optional manual unit placed inside guide articles (<InArticleAd /> in MDX).
export const ADSENSE_IN_ARTICLE_SLOT = /^\d{6,20}$/.test(process.env.NEXT_PUBLIC_ADSENSE_SLOT_IN_ARTICLE ?? "")
  ? (process.env.NEXT_PUBLIC_ADSENSE_SLOT_IN_ARTICLE as string)
  : "";

// ads.txt line authorizing Google to sell this site's inventory. The
// certification authority ID f08c47fec0942fa0 is Google's, the same for
// every publisher.
export function adsTxt(): string | null {
  if (!ADSENSE_CLIENT) return null;
  return `google.com, ${ADSENSE_CLIENT.replace(/^ca-/, "")}, DIRECT, f08c47fec0942fa0\n`;
}
