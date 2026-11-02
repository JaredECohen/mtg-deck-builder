// Rubric for reviewed guides. A guide with reviewed: true must clear every
// check or CI fails. Everything else is reported as excluded from the sitemap
// (the site noindexes it, or archived: true keeps it off the site entirely).

import fs from "node:fs";
import path from "node:path";

import matter from "gray-matter";

import { claimProblems, legacyClaimProblems } from "./guide-claims.mjs";

const DISCLOSURE = "may earn a commission";
const AFFILIATE_URL = /pxf\.io|partner\.tcgplayer\.com|manapool\.com\/[^\s)]*(?:ref|aff|partner)/i;

export function wordCount(body) {
  const text = body.replace(/<[^>]+>/g, " ").replace(/[#>*_`|-]/g, " ");
  return text.split(/\s+/).filter(Boolean).length;
}

export function reviewPost({ file, data, body, exampleIds, claims = null, facts = null, catalog = null }) {
  const problems = [];
  const fail = (message) => problems.push(`${file}: ${message}`);
  if (data.archived === true) fail("reviewed guide is also archived");
  if (!data.author) fail("missing author");
  const updated = data.updated instanceof Date ? data.updated.toISOString().slice(0, 10) : String(data.updated ?? "");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(updated)) fail(`missing or bad updated date "${updated}"`);
  const words = wordCount(body);
  if (words < 900) fail(`${words} words (reviewed guides need at least 900)`);
  if (!body.includes("## Short answer")) fail('missing "## Short answer"');
  if (!/^\| .+\|$/m.test(body)) fail("missing a decision table");
  if (!body.includes("## Common mistakes")) fail('missing "## Common mistakes"');
  if (!body.includes("## FAQ")) fail('missing "## FAQ"');
  if (!body.includes("## How this was made")) fail('missing "## How this was made"');
  if (!body.includes("<FanContentNotice")) fail("missing the Wizards Fan Content notice");
  if (!body.includes("MTGJSON") || !body.includes("Scryfall")) fail("missing MTGJSON and Scryfall source names");
  if (!/20\d{2}-\d{2}-\d{2}/.test(body)) fail("missing a fetched-at date on the sourced claims");
  if (!body.includes("$")) fail("missing a sourced dollar figure");
  const deckIds = [...body.matchAll(/<DeckBlock\s+id="([^"]+)"/g)].map((match) => match[1]);
  if (!deckIds.length) fail("missing a DeckBlock (the ?example= deck link)");
  for (const id of deckIds) {
    if (!exampleIds.has(id)) fail(`DeckBlock id "${id}" is not in the example catalog`);
  }
  const affiliate = AFFILIATE_URL.test(body);
  const disclosure = body.includes(DISCLOSURE);
  if (affiliate && !disclosure) fail("affiliate link without the disclosure");
  if (disclosure && !affiliate) fail("affiliate disclosure but no affiliate link on the page");
  if (claims) {
    for (const problem of claimProblems({ file, body, claims, facts })) problems.push(problem);
  } else if (catalog) {
    for (const problem of legacyClaimProblems({ file, body, catalog, exampleIds })) problems.push(problem);
  }
  return problems;
}

export function loadExampleIds(catalogPath) {
  const catalog = JSON.parse(fs.readFileSync(catalogPath, "utf8"));
  return new Set(Object.keys(catalog.decks ?? {}));
}

export function loadPosts(blogDir) {
  return fs
    .readdirSync(blogDir)
    .filter((file) => file.endsWith(".mdx"))
    .map((file) => {
      const raw = fs.readFileSync(path.join(blogDir, file), "utf8");
      const { data, content } = matter(raw);
      return { file, slug: file.replace(/\.mdx$/, ""), data, body: content };
    });
}
