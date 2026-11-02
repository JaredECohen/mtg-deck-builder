import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { AUTHOR, GUIDE_AUTHOR, allPosts, articleCredit } from "./blog";

const webRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

test("only a reviewed guide is signed Deck Lab Editorial and points at the method", () => {
  const posts = allPosts();
  const reviewed = posts.filter((post) => post.reviewed);
  const unreviewed = posts.filter((post) => !post.reviewed);
  assert.ok(reviewed.length >= 1);
  assert.ok(unreviewed.length >= 1);
  for (const post of reviewed) {
    const credit = articleCredit(post);
    assert.equal(credit.byline, GUIDE_AUTHOR);
    assert.equal(credit.showMethod, true);
  }
  for (const post of unreviewed) {
    const credit = articleCredit(post);
    assert.notEqual(credit.byline, GUIDE_AUTHOR);
    assert.equal(credit.byline, post.author || AUTHOR);
    assert.equal(credit.showMethod, false);
  }

  const page = fs.readFileSync(path.join(webRoot, "src/app/blog/[slug]/page.tsx"), "utf8");
  assert.match(page, /credit\.showMethod \?/);
  assert.match(page, /How we count/);
  const method = fs.readFileSync(path.join(webRoot, "src/app/method/page.tsx"), "utf8");
  assert.match(method, /Reviewed guides signed Deck Lab Editorial/);
  assert.match(method, /has not passed the rubric/);
  assert.doesNotMatch(method, /Guides signed Deck Lab Editorial cite/);
});
