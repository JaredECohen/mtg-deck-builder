// CI entry point: node scripts/check-guide-rubric.mjs
//
// Reviewed guides must pass. Archived guides cannot publish. Every other
// guide is listed as excluded from the sitemap (the site also noindexes it).

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { factNames, similarityProblems } from "./guide-claims.mjs";
import { loadExampleIds, loadPosts, reviewPost } from "./guide-rubric.mjs";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const blogDir = path.join(root, "content", "blog");
const catalogPath = path.join(root, "src", "data", "example-decks.json");
const factsPath = path.join(root, "src", "data", "precon_facts.json");
const exampleIds = loadExampleIds(catalogPath);
const catalog = JSON.parse(fs.readFileSync(catalogPath, "utf8"));
const facts = fs.existsSync(factsPath) ? JSON.parse(fs.readFileSync(factsPath, "utf8")) : null;
const posts = loadPosts(blogDir);

const failures = [];
const passed = [];
const excluded = [];

for (const post of posts) {
  if (post.data.reviewed === true) {
    const claimsPath = path.join(blogDir, `${post.slug}.claims.json`);
    const claims = fs.existsSync(claimsPath) ? JSON.parse(fs.readFileSync(claimsPath, "utf8")) : null;
    const problems = reviewPost({ ...post, exampleIds, claims, facts, catalog: claims ? null : catalog });
    if (problems.length) failures.push(...problems);
    else passed.push(post.slug);
    continue;
  }
  if (post.data.archived === true) excluded.push(`${post.slug}: archived (not published)`);
  else excluded.push(`${post.slug}: not reviewed (noindex, omitted from sitemap)`);
}

console.log(`Reviewed guides passing: ${passed.length}`);
for (const slug of passed.sort()) console.log(`  PASS ${slug}`);
console.log(`Excluded from publishing/sitemap: ${excluded.length}`);
if (process.env.RUBRIC_VERBOSE === "1") {
  for (const line of excluded) console.log(`  ${line}`);
}
const reviewed = posts.filter((post) => post.data.reviewed === true);
const duplicates = similarityProblems(reviewed, undefined, factNames(facts, catalog));
if (duplicates.length) failures.push(...duplicates);

if (failures.length) {
  console.error(`${failures.length} rubric failure(s):\n  ${failures.join("\n  ")}`);
  process.exit(1);
}
console.log("Guide rubric OK.");
