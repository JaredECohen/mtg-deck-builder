import { SITE_NAME } from "@/lib/blog";

/** Search-result titles are about 60 characters. Descriptions are about 160. */
export const TITLE_MAX = 60;
export const DESCRIPTION_MAX = 160;

/** Site-wide social card. Deck pages replace this with their own image. */
export const DEFAULT_SOCIAL_IMAGE = {
  url: "/opengraph-image",
  width: 1200,
  height: 630,
  alt: "MTG Deck Lab, a free Magic: The Gathering deck builder",
} as const;

function clip(text: string, max: number): string {
  const value = text.trim().replace(/\s+/g, " ");
  if (value.length <= max) return value;
  const cut = value.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  const base = (space >= 40 ? cut.slice(0, space) : cut).trimEnd().replace(/[|:;,.–—-]+$/u, "");
  return `${base}…`;
}

/**
 * Document title. Keep " | MTG Deck Lab" when the pair fits. Otherwise use the
 * specific title, clipped to TITLE_MAX. Guide H1s stay the full frontmatter
 * title; only the `<title>` tag is shortened.
 */
export function documentTitle(specific: string, siteName: string = SITE_NAME): string {
  const title = specific.trim().replace(/\s+/g, " ");
  const branded = `${title} | ${siteName}`;
  if (branded.length <= TITLE_MAX) return branded;
  return clip(title, TITLE_MAX);
}

/** Open Graph / Twitter title. The site name is a separate tag, so it is not repeated. */
export function socialTitle(specific: string): string {
  return clip(specific.trim().replace(/\s+/g, " "), TITLE_MAX);
}

/**
 * Meta description. Prefer a sentence boundary inside the limit so a claim is
 * not cut in half. The guide page still shows the full frontmatter description.
 */
export function metaDescription(description: string, max: number = DESCRIPTION_MAX): string {
  const text = description.trim().replace(/\s+/g, " ");
  if (text.length <= max) return text;
  const window = text.slice(0, max + 1);
  let sentence = -1;
  for (const mark of [". ", "! ", "? "]) {
    sentence = Math.max(sentence, window.lastIndexOf(mark));
  }
  if (sentence >= 80) return text.slice(0, sentence + 1);
  return clip(text, max);
}
