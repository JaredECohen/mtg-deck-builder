import assert from "node:assert/strict";
import test from "node:test";

import { indexableBlogPath, isIndexableHub } from "./blog";

test("blog links resolve only to reviewed guides and indexable hubs", () => {
  assert.equal(isIndexableHub("deck-archetypes"), true);
  assert.equal(isIndexableHub("formats"), false);
  assert.equal(isIndexableHub("strategy"), false);
  assert.equal(isIndexableHub("learn-to-play"), false);
  assert.equal(isIndexableHub("sets"), false);
  assert.equal(indexableBlogPath("/blog/should-you-play-aggro"), "/blog/should-you-play-aggro");
  assert.equal(indexableBlogPath("/blog/deck-archetypes"), "/blog/deck-archetypes");
  assert.equal(indexableBlogPath("/blog/formats"), null);
  assert.equal(indexableBlogPath("/blog/learn-to-play"), null);
  assert.equal(indexableBlogPath("/blog/sets"), null);
  assert.equal(indexableBlogPath("/blog/your-first-game-of-magic"), null);
  assert.equal(indexableBlogPath("/blog/the-hobbit-mtg-set-guide"), null);
  assert.equal(indexableBlogPath("/blog/secrets-of-strixhaven-mtg-set-guide"), null);
});
