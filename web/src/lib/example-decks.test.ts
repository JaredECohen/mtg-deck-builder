import assert from "node:assert/strict";
import test from "node:test";

import { exampleBuilderHref, prepopulateFromExample } from "./example-decks";

test("?example= prepopulates the official burn list", () => {
  const deck = prepopulateFromExample("mono-red-burn");
  assert.ok(deck);
  assert.equal(deck.format, "pioneer");
  assert.equal(deck.commander, "");
  const mountains = deck.mainboard.find((card) => card.name === "Mountain");
  assert.ok(mountains && mountains.quantity >= 16);
  assert.equal(deck.mainboard.reduce((sum, card) => sum + card.quantity, 0), 60);
  assert.equal(exampleBuilderHref("mono-red-burn"), "/?example=mono-red-burn#builder");
});

test("an unknown example id does not invent a deck", () => {
  assert.equal(prepopulateFromExample("not-a-real-deck"), null);
  assert.equal(prepopulateFromExample(null), null);
  assert.equal(prepopulateFromExample(""), null);
});
