import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { exampleBuilderHref, getExampleDeck, listExampleDeckIds, loadCachedPromise, prepopulateFromExample, readExampleDeck, resolveAnalyzeSeed } from "./example-decks";

test("?example= prepopulates the official burn list", async () => {
  const deck = await prepopulateFromExample("mono-red-burn");
  assert.ok(deck);
  assert.equal(deck.format, "pioneer");
  assert.equal(deck.commander, "");
  const mountains = deck.mainboard.find((card) => card.name === "Mountain");
  assert.ok(mountains && mountains.quantity >= 16);
  assert.equal(deck.mainboard.reduce((sum, card) => sum + card.quantity, 0), 60);
  assert.equal(exampleBuilderHref("mono-red-burn"), "/?example=mono-red-burn#builder");
});

test("world championship examples prefill as legacy and do not throw", async () => {
  const worlds = (await listExampleDeckIds()).filter((id) => id.startsWith("wc-"));
  assert.ok(worlds.length >= 30, `expected World Championship decks, found ${worlds.length}`);
  const deck = await prepopulateFromExample(worlds[0]);
  assert.ok(deck);
  assert.equal(deck.format, "legacy");
  assert.equal(deck.commander, "");
  assert.ok(deck.mainboard.length > 0);
  assert.equal(deck.mainboard.every((card) => card.name && card.quantity > 0), true);
});

test("an unknown example id does not invent a deck", async () => {
  assert.equal(await prepopulateFromExample("not-a-real-deck"), null);
  assert.equal(await prepopulateFromExample(null), null);
  assert.equal(await prepopulateFromExample(""), null);
});

test("prototype keys are not decks and do not throw", async () => {
  for (const id of ["constructor", "__proto__", "toString", "valueOf", "hasOwnProperty"]) {
    assert.equal(await getExampleDeck(id), null);
    assert.equal(await prepopulateFromExample(id), null);
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

test("the builder imports the slim list only when an example id is resolved", () => {
  const source = fs.readFileSync(path.join(path.dirname(fileURLToPath(import.meta.url)), "example-decks.ts"), "utf8");
  assert.match(source, /import\(\s*["']\.\.\/data\/example-deck-lists\.json["']\s*\)/);
  assert.doesNotMatch(source, /import\s+\w+\s+from\s+["'][^"']*example-deck-lists\.json["']/);
  assert.equal(source.includes("example-decks.json"), false);
  const workflow = fs.readFileSync(
    path.join(path.dirname(fileURLToPath(import.meta.url)), "../components/workshop/analyze-workflow.tsx"),
    "utf8",
  );
  assert.match(workflow, /if \(exampleId\) \{[\s\S]*prepopulateFromExample\(exampleId\)/);
});

test("veloci-ramp-tor keeps Dinosaur Egg and is a full commander list", async () => {
  const deck = await prepopulateFromExample("veloci-ramp-tor");
  assert.ok(deck);
  const egg = deck.mainboard.find((card) => card.name === "Dinosaur Egg");
  assert.ok(egg && egg.quantity === 1);
  const main = deck.mainboard.reduce((sum, card) => sum + card.quantity, 0);
  assert.equal(main + (deck.commander ? 1 : 0), 100);
});

test("the Aeo Paquette World Championship list keeps its Ornithopters", async () => {
  const deck = await prepopulateFromExample("wc-aeopaquetteaffinity-wc04");
  assert.ok(deck);
  const thopters = deck.mainboard.find((card) => card.name === "Ornithopter");
  assert.ok(thopters && thopters.quantity === 4);
  assert.match(deck.note, /Vintage\/Old School example/);
});

test("loading an example does not adopt or replace the saved draft", async () => {
  const example = await prepopulateFromExample("mono-red-burn");
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

test("a failed example-list import can be retried and the saved draft still loads", async () => {
  const cache: { current: Promise<string> | null } = { current: null };
  let calls = 0;
  const start = () => {
    calls += 1;
    return Promise.reject(new Error("chunk failed"));
  };
  await assert.rejects(() => loadCachedPromise(cache, start), /chunk failed/);
  assert.equal(cache.current, null);
  await assert.rejects(() => loadCachedPromise(cache, start), /chunk failed/);
  assert.equal(calls, 2);

  const seed = resolveAnalyzeSeed({
    example: null,
    draft: {
      format: "commander",
      mainboard: [{ name: "My Draft Card", quantity: 1 }],
      notes: "keep this",
    },
    defaultNotes: "fallback",
  });
  assert.equal(seed.persistDraft, true);
  assert.equal(seed.format, "commander");
  assert.equal(seed.notes, "keep this");
  assert.equal(seed.mainboard[0]?.name, "My Draft Card");

  const workflow = fs.readFileSync(
    path.join(path.dirname(fileURLToPath(import.meta.url)), "../components/workshop/analyze-workflow.tsx"),
    "utf8",
  );
  assert.match(workflow, /catch \{[\s\S]*example = null;/);
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
