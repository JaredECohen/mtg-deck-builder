import { notFound } from "next/navigation";

import { deckCardImage } from "@/lib/deck-og-image";
import { fetchPublicDeck } from "@/lib/public-deck";

export const alt = "Magic deck preview";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export default async function Image({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  const deck = await fetchPublicDeck(token);
  if (!deck) notFound();
  return deckCardImage(deck);
}
