import assert from "node:assert/strict";
import test from "node:test";

import { reviewFailures } from "./check-guide-rubric.mjs";

test("no reviewed guide fails the rubric or the review gates", () => {
  const { failures, passed, reviewed, gateSlugs } = reviewFailures();
  assert.deepEqual(gateSlugs, []);
  assert.deepEqual(failures, []);
  assert.deepEqual(passed.sort(), reviewed.sort());
  assert.ok(reviewed.length >= 1);
});
