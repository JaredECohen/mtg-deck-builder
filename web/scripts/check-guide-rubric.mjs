// CI entry point: node scripts/check-guide-rubric.mjs
//
// Reviewed guides must pass. Archived guides cannot publish. Every other
// guide is listed as excluded from the sitemap (the site also noindexes it).

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { factNames, similarityProblems } from "./guide-claims.mjs";
import { loadOracle, loadRules, outlineGateProblems, reviewGateProblems } from "./review-gates.mjs";
import { loadExampleIds, loadPosts, reviewPost } from "./guide-rubric.mjs";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const blogDir = path.join(root, "content", "blog");
const catalogPath = path.join(root, "src", "data", "example-decks.json");
const factsPath = path.join(root, "src", "data", "precon_facts.json");
const oraclePath = path.join(root, "src", "data", "scryfall-oracle-index.json");
const rulesPath = path.join(root, "content", "rules", "MagicCompRules-20261106.txt");
const officialPath = path.join(root, "..", "api", "app", "data", "official_decks.json");
const exampleIds = loadExampleIds(catalogPath);
const catalog = JSON.parse(fs.readFileSync(catalogPath, "utf8"));
const facts = fs.existsSync(factsPath) ? JSON.parse(fs.readFileSync(factsPath, "utf8")) : null;
const oracle = fs.existsSync(oraclePath) ? loadOracle(oraclePath) : null;
const rules = fs.existsSync(rulesPath) ? loadRules(rulesPath) : null;
const deckNames = [
  ...Object.values(catalog.decks ?? {}).map((deck) => deck.name),
  ...Object.values(facts?.decks ?? {}).map((deck) => deck?.name),
].filter(Boolean);

function cardNames(card) {
  const name = typeof card === "string" ? card : card?.name;
  if (!name) return [];
  const names = [name];
  if (name.includes(" // ")) names.push(name.split(" // ")[0]);
  return names;
}

const deckCards = fs.existsSync(officialPath)
  ? JSON.parse(fs.readFileSync(officialPath, "utf8")).decks.map((deck) => ({
      name: deck.name,
      cards: [...(deck.mainboard ?? []), ...(deck.sideboard ?? []), ...(deck.commanders ?? [])].flatMap(cardNames),
    }))
  : [];
const posts = loadPosts(blogDir);

/** Rubric and review-gate failures for every reviewed guide. No exemptions. */
export function reviewFailures() {
  const failures = [];
  const passed = [];
  const excluded = [];
  const gateBySlug = new Map();

  for (const post of posts) {
    if (post.data.reviewed === true) {
      const claimsPath = path.join(blogDir, `${post.slug}.claims.json`);
      const claims = fs.existsSync(claimsPath) ? JSON.parse(fs.readFileSync(claimsPath, "utf8")) : null;
      const problems = reviewPost({ ...post, exampleIds, claims, facts, catalog: claims ? null : catalog, deckCards });
      if (problems.length) failures.push(...problems);
      else passed.push(post.slug);
      const gate = reviewGateProblems({ file: post.file, body: post.body, oracle, rules, catalog, deckNames, claims });
      if (gate.length) gateBySlug.set(post.slug, gate);
      continue;
    }
    if (post.data.archived === true) excluded.push(`${post.slug}: archived (not published)`);
    else excluded.push(`${post.slug}: not reviewed (noindex, omitted from sitemap)`);
  }

  const reviewed = posts.filter((post) => post.data.reviewed === true);
  const duplicates = similarityProblems(reviewed, undefined, factNames(facts, catalog));
  for (const problem of duplicates) {
    if (problem.includes("section outline")) continue;
    failures.push(problem);
  }
  const outlineWith = new Map();
  for (const problem of outlineGateProblems(reviewed)) {
    const slugs = [...problem.matchAll(/([a-z0-9-]+)\.mdx/g)].map((match) => match[1]);
    const score = problem.match(/Jaccard ([0-9.]+)/)?.[1] ?? "";
    for (const slug of slugs) {
      const others = outlineWith.get(slug) ?? [];
      for (const other of slugs) {
        if (other !== slug) others.push(`${other} (${score})`);
      }
      outlineWith.set(slug, others);
    }
  }
  for (const [slug, others] of outlineWith) {
    const list = gateBySlug.get(slug) ?? [];
    list.push(`${slug}.mdx: section outline matches ${[...new Set(others)].sort().join(", ")}`);
    gateBySlug.set(slug, list);
  }
  for (const slug of [...gateBySlug.keys()].sort()) {
    const unique = [...new Set(gateBySlug.get(slug))];
    failures.push(...unique.map((line) => (line.startsWith(slug) ? line : `${slug}: ${line}`)));
  }

  return { failures, passed, excluded, reviewed: reviewed.map((post) => post.slug), gateSlugs: [...gateBySlug.keys()] };
}

function report() {
  const { failures, passed, excluded, gateSlugs, reviewed } = reviewFailures();
  console.log(`Reviewed guides passing: ${passed.length}`);
  for (const slug of [...passed].sort()) console.log(`  PASS ${slug}`);
  console.log(`Excluded from publishing/sitemap: ${excluded.length}`);
  if (process.env.RUBRIC_VERBOSE === "1") {
    for (const line of excluded) console.log(`  ${line}`);
  }
  console.log(`Review gates (required for reviewed: true):`);
  if (!gateSlugs.length) console.log("  all reviewed guides pass");
  const gatePass = reviewed.filter((slug) => !gateSlugs.includes(slug)).sort();
  for (const slug of [...gateSlugs].sort()) console.log(`  FAIL ${slug}`);
  for (const slug of gatePass) console.log(`  PASS ${slug}`);
  if (failures.length) {
    console.error(`${failures.length} rubric failure(s):\n  ${failures.join("\n  ")}`);
    process.exit(1);
  }
  console.log("Guide rubric OK.");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  report();
}
