// Validates every guide in web/content/blog before it ships (CI runs this).
//
//   node scripts/check-guides.mjs
//
// Checks, per article:
// - frontmatter: title, description (120-170 chars), date, known category
// - one article per publishing day (the drip schedule)
// - internal /blog links and `related` slugs resolve to a guide or category.
//   Links to a guide scheduled later are fine: they render as plain text
//   until it publishes (mdx-components Anchor), and `related` skips it.
// - no bare {...} outside code: MDX evaluates it as JavaScript ({2} renders
//   "2", {U} breaks the build)
// - a <DeckLabCTA> with a supported format, two <InArticleAd /> breaks on
//   their own lines, no "# " h1 in the body
// - body length 900-3,500 words

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import matter from "gray-matter";

const BLOG_DIR = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "content", "blog");
const CATEGORIES = new Set(["learn-to-play", "formats", "deck-archetypes", "strategy"]);
const FORMATS = new Set(["standard", "modern", "pioneer", "legacy", "commander"]);

const asDate = (value) => (value instanceof Date ? value.toISOString().slice(0, 10) : String(value ?? ""));

const files = fs.readdirSync(BLOG_DIR).filter((file) => file.endsWith(".mdx"));
const posts = files.map((file) => {
  const { data, content } = matter(fs.readFileSync(path.join(BLOG_DIR, file), "utf8"));
  return { file, slug: file.replace(/\.mdx$/, ""), data, body: content, date: asDate(data.date) };
});
const live = posts.filter((post) => post.data.draft !== true);
const dateOf = new Map(live.map((post) => [post.slug, post.date]));
const firstDate = live.reduce((min, post) => (post.date < min ? post.date : min), "9999-12-31");

const problems = [];
const byDate = new Map();

for (const post of live) {
  const fail = (message) => problems.push(`${post.file}: ${message}`);
  const { data, body, date } = post;

  if (!data.title) fail("missing title");
  const description = String(data.description ?? "");
  if (description.length < 120 || description.length > 170) fail(`description is ${description.length} chars (want 120-170)`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) fail(`bad date "${date}"`);
  if (!CATEGORIES.has(String(data.category))) fail(`unknown category "${data.category}"`);

  // The launch batch shares its first day; after that, one article per day.
  if (date !== firstDate) {
    if (byDate.has(date)) fail(`shares publish date ${date} with ${byDate.get(date)}`);
    byDate.set(date, post.file);
  }

  for (const [, slug] of body.matchAll(/\]\(\/blog\/([a-z0-9-]+)(?:#[^)]*)?\)/g)) {
    if (!CATEGORIES.has(slug) && !dateOf.has(slug)) fail(`broken link /blog/${slug}`);
  }
  for (const slug of Array.isArray(data.related) ? data.related : []) {
    if (!dateOf.has(slug)) fail(`related slug "${slug}" doesn't exist`);
  }
  // Every guide needs at least one link that works on its publish day.
  const liveLinks = [...body.matchAll(/\]\(\/blog\/([a-z0-9-]+)/g)].filter(
    ([, slug]) => CATEGORIES.has(slug) || (dateOf.get(slug) ?? "9999") <= date,
  );
  if (!liveLinks.length) fail("no /blog link that is live on its publish day");

  const prose = body
    .replace(/```[\s\S]*?```/g, "")
    .replace(/`[^`]*`/g, "")
    .replace(/<[A-Z][^>]*\/?>/g, "");
  for (const [brace] of prose.matchAll(/\{[^}]*\}/g)) fail(`bare ${brace} (wrap mana symbols in backticks)`);

  const ctas = [...body.matchAll(/<DeckLabCTA\b[^>]*>/g)];
  if (!ctas.length) fail("no <DeckLabCTA />");
  for (const [tag] of ctas) {
    const format = tag.match(/format="([^"]+)"/)?.[1];
    if (format && !FORMATS.has(format)) fail(`DeckLabCTA format "${format}" isn't supported`);
  }
  const adLines = body.split("\n").filter((line) => line.includes("<InArticleAd"));
  if (adLines.length < 2) fail(`${adLines.length} <InArticleAd /> (want 2)`);
  for (const line of adLines) if (line.trim() !== "<InArticleAd />") fail("<InArticleAd /> must be alone on its line");
  if (/^# /m.test(body)) fail('body has a "# " h1 (the title is the h1)');

  const words = body.replace(/<[^>]+>|[#>*_`|-]/g, " ").split(/\s+/).filter(Boolean).length;
  if (words < 900 || words > 3500) fail(`${words} words (want 900-3,500)`);
}

const scheduled = live.filter((post) => post.date > new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date()));
if (problems.length) {
  console.error(`${problems.length} problem(s) in ${live.length} guides:\n  ${problems.join("\n  ")}`);
  process.exit(1);
}
console.log(`${live.length} guides OK (${scheduled.length} scheduled for later).`);
