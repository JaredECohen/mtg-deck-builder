// CI entry point: node scripts/check-guide-rubric.mjs
//
// Reviewed guides must pass. Archived guides cannot publish. Every other
// guide is listed as excluded from the sitemap (the site also noindexes it).

import path from "node:path";
import { fileURLToPath } from "node:url";

import { loadExampleIds, loadPosts, reviewPost } from "./guide-rubric.mjs";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const blogDir = path.join(root, "content", "blog");
const catalogPath = path.join(root, "src", "data", "example-decks.json");
const exampleIds = loadExampleIds(catalogPath);
const posts = loadPosts(blogDir);

const failures = [];
const passed = [];
const excluded = [];

for (const post of posts) {
  if (post.data.reviewed === true) {
    const problems = reviewPost({ ...post, exampleIds });
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
if (failures.length) {
  console.error(`${failures.length} rubric failure(s):\n  ${failures.join("\n  ")}`);
  process.exit(1);
}
console.log("Guide rubric OK.");
