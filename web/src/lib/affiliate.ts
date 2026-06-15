// TCGplayer affiliate link construction for client-built links (deck-level
// shopping list + "buy entire deck" mass entry). Per-card product links come
// from the API already affiliate-wrapped; this covers surfaces where we only
// have card names. The Impact deep-link prefix is inlined at build time from
// NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL, e.g.
//   https://tcgplayer.pxf.io/c/123456/789012/21018

const AFFILIATE_PREFIX = process.env.NEXT_PUBLIC_TCGPLAYER_AFFILIATE_URL ?? "";

const SEARCH_BASE = "https://www.tcgplayer.com/search/magic/product";
const MASS_ENTRY_BASE = "https://www.tcgplayer.com/massentry";

// Wrap a tcgplayer.com destination in the Impact deep link when configured.
export function tcgplayerAffiliate(destinationUrl: string): string {
  if (!destinationUrl) return destinationUrl;
  if (!AFFILIATE_PREFIX || destinationUrl.includes("pxf.io")) return destinationUrl;
  return `${AFFILIATE_PREFIX}?u=${encodeURIComponent(destinationUrl)}`;
}

// Affiliate-tracked TCGplayer search URL for a single card by name.
export function tcgplayerSearchUrl(cardName: string): string {
  const dest = `${SEARCH_BASE}?q=${encodeURIComponent(cardName)}&productLineName=magic`;
  return tcgplayerAffiliate(dest);
}

// Affiliate-tracked TCGplayer Mass Entry URL for a whole decklist — a single
// cart pre-filled with every card at the cheapest available sellers.
export function tcgplayerMassEntryUrl(entries: Array<{ name: string; quantity: number }>): string {
  const lines = entries
    .filter((e) => e.name && e.quantity > 0)
    .map((e) => `${e.quantity} ${e.name}`)
    .join("||");
  const dest = `${MASS_ENTRY_BASE}?productline=Magic&c=${encodeURIComponent(lines)}`;
  return tcgplayerAffiliate(dest);
}

// Disclosure shown wherever affiliate links appear.
export const AFFILIATE_DISCLOSURE =
  "Buy links are TCGplayer affiliate links — this site may earn a commission on purchases at no extra cost to you.";
