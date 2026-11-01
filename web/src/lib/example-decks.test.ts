import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { exampleBuilderHref, getExampleDeck, prepopulateFromExample, readExampleDeck, resolveAnalyzeSeed } from "./example-decks";

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

test("prototype keys are not decks and do not throw", () => {
  for (const id of ["constructor", "__proto__", "toString", "valueOf", "hasOwnProperty"]) {
    assert.equal(getExampleDeck(id), null);
    assert.equal(prepopulateFromExample(id), null);
  }
  const inherited = Object.create({
    toString: {
      name: "Inherited",
      format: "pioneer",
      commander: "",
      mainboard: [{ name: "Mountain", quantity: 60 }],
      sideboard: [],
    },
  });
  assert.equal(readExampleDeck(inherited, "toString"), null);
  assert.equal(readExampleDeck({ "bad-shape": { name: "Nope" } }, "bad-shape"), null);
});

test("the builder imports the slim list, not the priced catalog", () => {
  const source = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "example-decks.ts"), "utf8");
  assert.match(source, /example-deck-lists\.json/);
  assert.equal(source.includes("example-decks.json"), false);
});

test("a product token is not in the sleeveable list", () => {
  const deck = prepopulateFromExample("veloci-ramp-tor");
  assert.ok(deck);
  assert.equal(
    deck.mainboard.some((card) => card.name === "Dinosaur Egg"),
    false,
  );
});

test("loading an example does not adopt or replace the saved draft", () => {
  const example = prepopulateFromExample("mono-red-burn");
  assert.ok(example);
  const draft = {
    format: "commander" as const,
    mainboard: [{ name: "My Draft Card", quantity: 1 }],
    sideboard: [],
    commander: "Atraxa, Praetors' Voice",
    notes: "keep this",
  };
  const seeded = resolveAnalyzeSeed({ example, draft, defaultNotes: "fallback" });
  assert.equal(seeded.persistDraft, false);
  assert.equal(seeded.format, "pioneer");
  assert.equal(seeded.commander, "");
  assert.equal(
    seeded.mainboard.some((card) => card.name === "My Draft Card"),
    false,
  );
  assert.match(seeded.notes, /Mono-Red Burn/);

  const restored = resolveAnalyzeSeed({ example: null, draft, defaultNotes: "fallback" });
  assert.equal(restored.persistDraft, true);
  assert.equal(restored.format, "commander");
  assert.equal(restored.commander, "Atraxa, Praetors' Voice");
  assert.equal(restored.notes, "keep this");
  assert.equal(restored.mainboard[0]?.name, "My Draft Card");
});

test("the analyze workflow refuses to autosave an example over the draft", () => {
  const workflow = fs.readFileSync(
    path.join(path.dirname(fileURLToPath(import.meta.url)), "../components/workshop/analyze-workflow.tsx"),
    "utf8",
  );
  assert.match(workflow, /persistDraft\.current = seed\.persistDraft/);
  assert.match(workflow, /if \(!draftHydrated \|\| !persistDraft\.current\) return;/);
  assert.match(workflow, /if \(persistDraft\.current\) clearManualDraft\(\)/);
});
