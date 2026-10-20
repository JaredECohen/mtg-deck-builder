// The guides section: MDX articles committed under web/content/blog.
//
// Publishing is scheduled by each article's `date`: a post is live once that
// day has arrived in New York (America/New_York), and hidden everywhere
// until then (index, hubs, related, sitemap, RSS, direct URL). Pages that
// list posts revalidate hourly (BLOG_REVALIDATE_SECONDS), so a post dated
// tomorrow appears tomorrow without a deploy.

import fs from "node:fs";
import path from "node:path";

import matter from "gray-matter";

export const SITE_URL = "https://mtgdecklab.app";
export const SITE_NAME = "MTG Deck Lab";
export const AUTHOR = "Jared Cohen";

const BLOG_DIR = path.join(process.cwd(), "content", "blog");

export const CATEGORIES = {
  "learn-to-play": {
    label: "Learn to Play",
    description:
      "New to Magic: The Gathering? Start here: how a game works, how to read a card, and the mistakes almost every new player makes.",
  },
  formats: {
    label: "Formats Explained",
    description:
      "Standard, Commander, Modern, Pioneer, Pauper and Limited: what each format is, which cards it allows, and who it suits.",
  },
  "deck-archetypes": {
    label: "Deck Archetypes & Styles",
    description:
      "Aggro, control, midrange, combo and tempo, plus the deckbuilding fundamentals behind them: mana curves, budgets and your first Commander deck.",
  },
  strategy: {
    label: "Strategy & Improvement",
    description: "Play better games: mulligans, sideboarding and the decisions that separate good players from great ones.",
  },
} as const;

export type CategoryId = keyof typeof CATEGORIES;

export function isCategory(value: string): value is CategoryId {
  return Object.prototype.hasOwnProperty.call(CATEGORIES, value);
}

/** Pages that list or render posts re-render at most this often. */
export const BLOG_REVALIDATE_SECONDS = 3600;

/** Today's date (YYYY-MM-DD) in New York, the publishing time zone. */
export function publishingToday(now: Date = new Date()): string {
  // Server-only override for previewing the schedule, e.g. GUIDES_TODAY=2026-11-01.
  const override = process.env.GUIDES_TODAY;
  if (override && /^\d{4}-\d{2}-\d{2}$/.test(override)) return override;
  return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(now);
}

export type PostMeta = {
  slug: string;
  title: string;
  description: string;
  date: string;
  updated: string;
  category: CategoryId;
  keywords: string[];
  related: string[];
  readingMinutes: number;
  wordCount: number;
};

export type Post = PostMeta & {
  body: string;
  toc: { id: string; title: string }[];
};

/** Heading text → anchor id. Shared with the MDX heading renderer. */
export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-");
}

function plainText(markdown: string): string {
  return markdown
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/[#>*_`|-]/g, " ");
}

function readPost(file: string): Post | null {
  const slug = file.replace(/\.mdx$/, "");
  const raw = fs.readFileSync(path.join(BLOG_DIR, file), "utf8");
  const { data, content } = matter(raw);
  if (data.draft === true) return null;
  if (!isCategory(String(data.category))) {
    throw new Error(`content/blog/${file}: unknown category "${data.category}"`);
  }
  for (const field of ["title", "description", "date"]) {
    if (!data[field]) throw new Error(`content/blog/${file}: missing frontmatter "${field}"`);
  }
  const wordCount = plainText(content).split(/\s+/).filter(Boolean).length;
  const toc = Array.from(content.matchAll(/^## (.+)$/gm), (match) => {
    const title = match[1].trim();
    return { id: slugify(title), title };
  });
  const asDate = (value: unknown) => (value instanceof Date ? value.toISOString().slice(0, 10) : String(value));
  return {
    slug,
    title: String(data.title),
    description: String(data.description),
    date: asDate(data.date),
    updated: asDate(data.updated ?? data.date),
    category: data.category as CategoryId,
    keywords: Array.isArray(data.keywords) ? data.keywords.map(String) : [],
    related: Array.isArray(data.related) ? data.related.map(String) : [],
    readingMinutes: Math.max(1, Math.round(wordCount / 230)),
    wordCount,
    body: content,
    toc,
  };
}

let cache: Post[] | null = null;

/** Every non-draft post, including scheduled ones, newest first. */
export function allPostsIncludingScheduled(): Post[] {
  if (cache) return cache;
  const files = fs.existsSync(BLOG_DIR) ? fs.readdirSync(BLOG_DIR).filter((f) => f.endsWith(".mdx")) : [];
  cache = files
    .map(readPost)
    .filter((post): post is Post => post !== null)
    .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : a.title.localeCompare(b.title)));
  return cache;
}

/** Published posts (dated today or earlier in New York), newest first. */
export function allPosts(): Post[] {
  const today = publishingToday();
  return allPostsIncludingScheduled().filter((post) => post.date <= today);
}

export function getPost(slug: string): Post | undefined {
  return allPosts().find((post) => post.slug === slug);
}

export function postsInCategory(category: CategoryId): Post[] {
  return allPosts().filter((post) => post.category === category);
}

/** Frontmatter `related` first, then other posts in the same category. */
export function relatedPosts(post: Post, limit = 3): Post[] {
  const picked: Post[] = [];
  for (const slug of post.related) {
    const match = getPost(slug);
    if (match && match.slug !== post.slug && !picked.includes(match)) picked.push(match);
  }
  for (const other of postsInCategory(post.category)) {
    if (picked.length >= limit) break;
    if (other.slug !== post.slug && !picked.includes(other)) picked.push(other);
  }
  return picked.slice(0, limit);
}

export function formatDate(iso: string): string {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
    timeZone: "UTC",
  });
}
