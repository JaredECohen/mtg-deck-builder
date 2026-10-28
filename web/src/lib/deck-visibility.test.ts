import assert from "node:assert/strict";
import test from "node:test";

import { visibilityForNewDeck } from "./deck-visibility";

test("the save control sends public unless the user hides the deck", () => {
  assert.equal(visibilityForNewDeck(false), "public");
  assert.equal(visibilityForNewDeck(true), "unlisted");
});
