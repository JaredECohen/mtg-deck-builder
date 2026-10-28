import assert from "node:assert/strict";
import test from "node:test";

import { visibilityForNewDeck } from "./deck-visibility";

test("a new deck stays unlisted unless the user chooses public", () => {
  assert.equal(visibilityForNewDeck(false), "unlisted");
  assert.equal(visibilityForNewDeck(true), "public");
});
