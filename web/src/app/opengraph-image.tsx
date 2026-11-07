import { siteCardImage } from "@/lib/site-og-image";

export const alt = "MTG Deck Lab, a free Magic: The Gathering deck builder";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const runtime = "nodejs";

export default function Image() {
  return siteCardImage();
}
