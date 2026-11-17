import assert from "node:assert/strict";
import test from "node:test";

import { dataTableProblems, legalityProblems, manaValueTableProblems, reviewGateProblems, rulesProblems, sourcedClaimProblems, unresolvedCardNames } from "./review-gates.mjs";

const oracle = {
  fetched_at: "2026-11-01",
  formats: ["pioneer", "commander"],
  byLower: new Map([
    ["lightning bolt", { name: "Lightning Bolt", packed: "LL" }],
    ["expressive iteration", { name: "Expressive Iteration", packed: "BL" }],
    ["rampant growth", { name: "Rampant Growth", packed: "LL" }],
  ]),
  sets: new Set(["the lost caverns of ixalan", "lost caverns of ixalan"]),
};

const rules = {
  effective: "November 6, 2026",
  numbers: new Set(["100.1", "601.2a", "704.5f"]),
};

const catalog = {
  decks: {
    burn: {
      name: "Mono-Red Burn",
      mainboard: [{ name: "Lightning Bolt", quantity: 4 }],
      sideboard: [],
      analysis: { total_cost_usd: 31.38, land_count: 20 },
    },
  },
};

test("a title-case card name must resolve in the Scryfall index", () => {
  const problems = unresolvedCardNames("The list plays Lightning Bolt and Not A Real Card.", oracle, ["Mono-Red Burn"]);
  assert.deepEqual(problems, ["Not A Real Card"]);
  assert.deepEqual(unresolvedCardNames("Lightning Bolt is the one-mana spell.", oracle, []), []);
});

test("a standalone one-word card name is checked, and a common word is not", () => {
  const flagged = unresolvedCardNames("Thoughtseize is banned in Modern. The list runs 4 Solitude. Play starts on turn one.", oracle, []);
  assert.ok(flagged.includes("Thoughtseize"));
  assert.ok(flagged.includes("Solitude"));
  assert.equal(flagged.includes("Play"), false);
  assert.equal(flagged.includes("Modern"), false);
  const header = unresolvedCardNames("| Lands | Price |\n| --- | --- |\n| Burn | $31.38 |", oracle, []);
  assert.equal(header.includes("Lands"), false);

  const withCounterspell = {
    ...oracle,
    byLower: new Map([...oracle.byLower, ["counterspell", { name: "Counterspell", packed: "LL" }]]),
  };
  const known = unresolvedCardNames("Counterspell is the two-mana answer.", withCounterspell, []);
  assert.equal(known.includes("Counterspell"), false);
});

test("a set name and a deck name are not unresolved cards", () => {
  const problems = unresolvedCardNames("Blood Rites is from Lost Caverns of Ixalan. Mono-Red Burn is the product.", oracle, ["Mono-Red Burn", "Blood Rites"]);
  assert.deepEqual(problems, []);
});

test("a legality sentence has to match the Scryfall index", () => {
  const banned = legalityProblems({
    file: "tempo.mdx",
    body: "Expressive Iteration is not legal in Pioneer today.",
    oracle,
    deckNames: [],
    catalog,
  });
  assert.deepEqual(banned, []);

  const wrong = legalityProblems({
    file: "tempo.mdx",
    body: "Expressive Iteration is legal in Pioneer today.",
    oracle,
    deckNames: [],
    catalog,
  });
  assert.ok(wrong.some((line) => line.includes("Expressive Iteration")));
});

test("a Comprehensive Rules citation must exist in the dated file", () => {
  assert.deepEqual(rulesProblems({ file: "rules.mdx", body: "See rule 601.2a.", rules }), []);
  const missing = rulesProblems({ file: "rules.mdx", body: "See rule 999.9z.", rules });
  assert.ok(missing.some((line) => line.includes("999.9z")));
  assert.deepEqual(rulesProblems({ file: "price.mdx", body: "The list is $157.27 and won 100.0%.", rules }), []);
});

test("a price, ban, or best-deck claim needs a sourced data file", () => {
  const bare = sourcedClaimProblems({ file: "thin.mdx", body: "The best deck costs $10 and Lightning Bolt is banned in Pioneer.", claims: null });
  assert.ok(bare.some((line) => line.includes("price")));
  assert.ok(bare.some((line) => line.includes("ban")));
  assert.ok(bare.some((line) => line.includes("best-deck")));
  const sourced = sourcedClaimProblems({
    file: "ok.mdx",
    body: 'The list costs $31.38.\n\n<DeckBlock id="burn" />',
    claims: null,
  });
  assert.deepEqual(sourced, []);
});

test("a reviewed guide needs a table whose numbers come from the data file", () => {
  const qualitative = dataTableProblems({
    file: "choice.mdx",
    body: "| Situation | Lean in |\n| --- | --- |\n| A long game | Walk away |",
    claims: null,
    catalog,
  });
  assert.ok(qualitative.some((line) => line.includes("table")));
  const priced = dataTableProblems({
    file: "census.mdx",
    body: '<DeckBlock id="burn" />\n\n| Deck | Lands | Price |\n| --- | --- | --- |\n| Mono-Red Burn | 20 | $31.38 |',
    claims: null,
    catalog,
  });
  assert.deepEqual(priced, []);

  const copiesOnly = dataTableProblems({
    file: "copies.mdx",
    body: '<DeckBlock id="burn" />\n\n| Card | Copies |\n| --- | --- |\n| Lightning Bolt | 4 |',
    claims: null,
    catalog,
  });
  assert.ok(copiesOnly.some((line) => line.includes("table")));

  const oneNumber = dataTableProblems({
    file: "one.mdx",
    body: '<DeckBlock id="burn" />\n\n| Deck | Lands |\n| --- | --- |\n| Mono-Red Burn | 20 |',
    claims: null,
    catalog,
  });
  assert.ok(oneNumber.some((line) => line.includes("table")));

  const declared = dataTableProblems({
    file: "declared.mdx",
    body: "| Deck | Lands |\n| --- | --- |\n| Mono-Red Burn | 20 |",
    claims: [{ text: "20", path: "summary.lands", as: "int" }],
    catalog,
  });
  assert.deepEqual(declared, []);
});

test("a mana value cell has to match the named card, so Dig Through Time at 7 fails", () => {
  const cardFacts = { cards: { "Dig Through Time": { cmc: 8 }, "Peer into the Abyss": { cmc: 7 } } };
  const wrong = "| Card | Copies | Mana value |\n| --- | --- | --- |\n| Dig Through Time | 2 | 7 |\n| Peer into the Abyss | 2 | 7 |\n";
  const problems = manaValueTableProblems({ file: "combo.mdx", body: wrong, cardFacts });
  assert.ok(problems.some((line) => line.includes("Dig Through Time") && line.includes("8") && line.includes("7")));
  assert.equal(problems.some((line) => line.includes("Peer into the Abyss")), false);
  const fixed = wrong.replace("| Dig Through Time | 2 | 7 |", "| Dig Through Time | 2 | 8 |");
  assert.deepEqual(manaValueTableProblems({ file: "combo.mdx", body: fixed, cardFacts }), []);
  const gated = reviewGateProblems({
    file: "combo.mdx",
    body: wrong,
    oracle,
    rules,
    catalog,
    deckNames: [],
    claims: null,
    cardFacts,
  });
  assert.ok(gated.some((line) => line.includes("Dig Through Time mana value is 8")));
});

test("a reviewed guide needs 1,000 words and the other gates", () => {
  const body = `## Short answer\n\n${"word ".repeat(1005)}\n\nLightning Bolt is legal in Pioneer.\n\n| Deck | Lands | Price |\n| --- | --- | --- |\n| Mono-Red Burn | 20 | $31.38 |\n\n<DeckBlock id="burn" />\n`;
  assert.deepEqual(
    reviewGateProblems({ file: "ok.mdx", body, oracle, rules, catalog, deckNames: ["Mono-Red Burn"], claims: null }),
    [],
  );
  const short = reviewGateProblems({
    file: "short.mdx",
    body: "Lightning Bolt is legal in Pioneer.\n\n| Deck | Price |\n| --- | --- |\n| Burn | $31.38 |\n\n<DeckBlock id=\"burn\" />\n",
    oracle,
    rules,
    catalog,
    deckNames: ["Mono-Red Burn"],
    claims: null,
  });
  assert.ok(short.some((line) => line.includes("words")));
});
