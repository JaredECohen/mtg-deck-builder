import assert from "node:assert/strict";
import { createRequire } from "node:module";
import test from "node:test";

import { categoryNavIds, indexableStaticPaths, isIndexableHub } from "./blog";

const require = createRequire(import.meta.url);
const { thinHubRedirects } = require("../../hub-redirects.cjs") as {
  thinHubRedirects: { source: string; destination: string; statusCode: number }[];
};
const nextConfig = require("../../next.config.js") as {
  redirects: () => Promise<{ source: string; destination: string; statusCode: number }[]>;
};

test("thin format and strategy hubs 301 to /blog and leave the nav and sitemap", async () => {
  assert.deepEqual(thinHubRedirects, [
    { source: "/blog/formats", destination: "/blog", statusCode: 301 },
    { source: "/blog/strategy", destination: "/blog", statusCode: 301 },
  ]);
  assert.deepEqual(await nextConfig.redirects(), thinHubRedirects);

  const paths = indexableStaticPaths();
  const nav = categoryNavIds();
  assert.equal(isIndexableHub("formats"), false);
  assert.equal(isIndexableHub("strategy"), false);
  assert.equal(isIndexableHub("deck-archetypes"), true);
  assert.deepEqual(nav, ["deck-archetypes"]);
  for (const rule of thinHubRedirects) {
    assert.equal(paths.includes(rule.source), false);
    assert.equal(nav.some((id) => rule.source === `/blog/${id}`), false);
  }
  assert.equal(paths.includes("/blog/deck-archetypes"), true);
  assert.equal(paths.includes("/blog/learn-to-play"), false);
  assert.equal(paths.includes("/blog/sets"), false);
  assert.equal(paths.includes("/terms"), true);
  assert.equal(paths.length, 25);
});
