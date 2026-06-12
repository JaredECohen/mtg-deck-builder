// Amazon affiliate link construction for client-built links (deck-level
// shopping list). Card-detail links come from the API already tagged; this
// covers surfaces where we only have a card name. The tag is inlined at
// build time from NEXT_PUBLIC_AMAZON_AFFILIATE_TAG.

const AFFILIATE_TAG = process.env.NEXT_PUBLIC_AMAZON_AFFILIATE_TAG ?? "";

export function amazonSearchUrl(cardName: string): string {
  const base = `https://www.amazon.com/s?k=${encodeURIComponent(`${cardName} magic the gathering card`)}`;
  return AFFILIATE_TAG ? `${base}&tag=${encodeURIComponent(AFFILIATE_TAG)}` : base;
}

// Required by the Amazon Associates operating agreement wherever
// affiliate links appear.
export const AFFILIATE_DISCLOSURE =
  "As an Amazon Associate, this site earns from qualifying purchases.";
