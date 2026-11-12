// TCGplayer affiliate link construction for client-built links (deck-level
// shopping list + "buy entire deck" mass entry) and for re-wrapping product
// URLs the API already tracked. The Impact deep-link prefix is inlined at
// build time from NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL, for example
//   https://partner.tcgplayer.com/c/123456/789012/21018
// NEXT_PUBLIC_TCGPLAYER_PARTNER_PROPERTY_ID is the media property id. It is
// appended as partnerpropertyid only when set. When the prefix is unset,
// helpers return a plain tcgplayer.com URL.
//
// subId1 is a short page tag so Impact can split earnings. Values are
// letters, digits, hyphen, and underscore, at most 64 characters:
//   home              homepage builder (Generate a deck: Shop This Deck)
//   workshop          card modal opened from Generate or Analyze
//   workshop-precon   precon upgrade cart, and the card modal on that tab
//   blog-<slug>       a reviewed guide, e.g. blog-mill-deck-guide
//   <path-slug>       any other page with a buy link (subIdFromPath)
// The API's own wrap uses "api". This module unwraps that (and any pxf.io
// or partner.tcgplayer.com wrapper) and re-wraps with the page tag.
// Unreviewed guides pass affiliate: false and stay untracked.

const AFFILIATE_HOSTS = ["pxf.io", "partner.tcgplayer.com"] as const;
const MAX_UNWRAP = 5;
const MAX_SUB_ID = 64;

export const TCG_SUB_ID = {
  home: "home",
  workshop: "workshop",
  workshopPrecon: "workshop-precon",
} as const;

export type AffiliateWrapOptions = {
  /** Impact subId1. Omitted when empty after sanitizing. */
  subId?: string;
  /** When false, return the canonical tcgplayer.com URL and do not wrap. */
  affiliate?: boolean;
};

function affiliatePrefix(): string {
  const raw = (process.env.NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL ?? "").trim();
  if (!raw) return "";
  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return "";
    const path = parsed.pathname.replace(/\/+$/, "");
    return `${parsed.origin}${path}`;
  } catch {
    return "";
  }
}

function readPartnerPropertyId(): string {
  return (process.env.NEXT_PUBLIC_TCGPLAYER_PARTNER_PROPERTY_ID ?? "").trim().replace(/[^A-Za-z0-9_-]/g, "");
}

/** Impact subId1: letters, digits, hyphen, underscore, at most 64 chars. */
export function sanitizeSubId(subId: string | null | undefined): string {
  if (!subId) return "";
  const cleaned = subId
    .trim()
    .replace(/[^A-Za-z0-9_-]+/g, "-")
    .replace(/-{2,}/g, "-")
    .replace(/^[-_]+|[-_]+$/g, "");
  return cleaned.slice(0, MAX_SUB_ID).replace(/^[-_]+|[-_]+$/g, "");
}

/** Reviewed-guide tag, e.g. blog-mill-deck-guide. */
export function blogSubId(slug: string): string {
  return sanitizeSubId(`blog-${slug}`);
}

/**
 * Short slug of a pathname for a page that is not one of the named surfaces.
 * "/" is home. "/blog/mill-deck-guide" is blog-mill-deck-guide.
 */
export function subIdFromPath(pathname: string): string {
  const path = pathname.trim().split("?")[0]?.split("#")[0] ?? "";
  if (!path || path === "/") return TCG_SUB_ID.home;
  const slug = path.split("/").filter(Boolean).slice(0, 4).join("-");
  return sanitizeSubId(slug);
}

function hostname(url: string): string {
  try {
    return new URL(url).hostname.toLowerCase();
  } catch {
    return "";
  }
}

function hostIs(host: string, domain: string): boolean {
  return host === domain || host.endsWith(`.${domain}`);
}

function isRedirector(url: string): boolean {
  const host = hostname(url);
  return AFFILIATE_HOSTS.some((domain) => hostIs(host, domain));
}

function isTcgplayerUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
    return hostIs(parsed.hostname.toLowerCase(), "tcgplayer.com");
  } catch {
    return false;
  }
}

/** Innermost destination, at most five affiliate wrappers deep. One decode per layer. */
export function canonicalTcgplayerUrl(url: string): string {
  let current = url;
  for (let i = 0; i < MAX_UNWRAP; i += 1) {
    if (!isRedirector(current)) return current;
    let inner: string | null = null;
    try {
      inner = new URL(current).searchParams.get("u");
    } catch {
      return current;
    }
    if (!inner) return current;
    current = inner;
  }
  return current;
}

/** True when a URL is actually wrapped for a commission, not a plain store link. */
export function isAffiliateUrl(url: string, prefix: string = affiliatePrefix()): boolean {
  if (!url) return false;
  if (isRedirector(url)) return true;
  if (!prefix) return false;
  return url.startsWith(prefix);
}

/** rel for an off-site link. Affiliate hosts (pxf.io and the TCGplayer partner host) are sponsored. */
export function externalAnchorRel(href: string): string {
  if (isAffiliateUrl(href)) return "sponsored nofollow noopener noreferrer";
  return "noopener noreferrer";
}

function wrapTracked(canonical: string, subId: string | undefined): string {
  const params: string[] = [];
  const safeSub = sanitizeSubId(subId);
  if (safeSub) params.push(`subId1=${encodeURIComponent(safeSub)}`);
  params.push(`u=${encodeURIComponent(canonical)}`);
  const propertyId = readPartnerPropertyId();
  if (propertyId) params.push(`partnerpropertyid=${encodeURIComponent(propertyId)}`);
  return `${affiliatePrefix()}?${params.join("&")}`;
}

/**
 * Unwrap pxf.io / partner.tcgplayer.com redirectors, then wrap with our prefix.
 * Refuses a destination that is not tcgplayer.com. With no prefix, or with
 * affiliate: false, returns the canonical tcgplayer.com URL.
 */
export function tcgplayerAffiliate(destinationUrl: string, options: AffiliateWrapOptions = {}): string {
  if (!destinationUrl) return destinationUrl;
  const canonical = canonicalTcgplayerUrl(destinationUrl);
  if (isRedirector(canonical) || !isTcgplayerUrl(canonical)) return "";
  if (options.affiliate === false || !affiliatePrefix()) return canonical;
  return wrapTracked(canonical, options.subId);
}

const SEARCH_BASE = "https://www.tcgplayer.com/search/magic/product";
const MASS_ENTRY_BASE = "https://www.tcgplayer.com/massentry";

// Affiliate-tracked TCGplayer search URL for a single card by name.
export function tcgplayerSearchUrl(cardName: string, options: AffiliateWrapOptions = {}): string {
  const dest = `${SEARCH_BASE}?q=${encodeURIComponent(cardName)}&productLineName=magic`;
  return tcgplayerAffiliate(dest, options);
}

/**
 * Product URL re-wrapped for this page, or a name search when the product
 * URL is missing or is not a TCGplayer link.
 */
export function tcgplayerBuyUrl(
  productUrl: string | null | undefined,
  cardName: string,
  options: AffiliateWrapOptions = {},
): string {
  const wrapped = productUrl ? tcgplayerAffiliate(productUrl, options) : "";
  return wrapped || tcgplayerSearchUrl(cardName, options);
}

// Affiliate-tracked TCGplayer Mass Entry URL for a whole decklist — a single
// cart pre-filled with every card at the cheapest available sellers.
export function tcgplayerMassEntryUrl(
  entries: Array<{ name: string; quantity: number }>,
  options: AffiliateWrapOptions = {},
): string {
  const lines = entries
    .filter((e) => e.name && e.quantity > 0)
    .map((e) => `${e.quantity} ${e.name}`)
    .join("||");
  const dest = `${MASS_ENTRY_BASE}?productline=Magic&c=${encodeURIComponent(lines)}`;
  return tcgplayerAffiliate(dest, options);
}

// Disclosure shown wherever affiliate links appear.
export const AFFILIATE_DISCLOSURE =
  "Buy links are TCGplayer affiliate links — this site may earn a commission on purchases at no extra cost to you.";
