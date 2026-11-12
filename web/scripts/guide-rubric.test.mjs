import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { cardDeckProblems, claimProblems, extractLiterals, formatFact, headlineLiteralProblems, legacyClaimProblems, legacyHeadlineProblems, similarityProblems } from "./guide-claims.mjs";
import { reviewPost } from "./guide-rubric.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const fixtureDir = path.join(scriptDir, "fixtures", "guide-rubric");
const root = path.join(scriptDir, "..");

const IDS = new Set(["mono-red-burn"]);

function reviewedBody(extra = "") {
  return `## Short answer

${"word ".repeat(920)}

| Situation | Lean in | Walk away |
| --- | --- | --- |
| A real choice | The measured list | A different plan |

<DeckBlock id="mono-red-burn" />

## Common mistakes

- Spending the answer on the wrong threat.

## FAQ

### Why these numbers?

They come from the fetch.

## How this was made

MTGJSON deck files and Scryfall oracle cards, fetched 2026-11-01. The total is $31.38.

<FanContentNotice />
${extra}`;
}

test("a thin reviewed guide fails the rubric", () => {
  const problems = reviewPost({
    file: "thin.mdx",
    data: { reviewed: true, author: "", updated: "soon" },
    body: "Not a guide.",
    exampleIds: IDS,
  });
  assert.ok(problems.some((line) => line.includes("missing author")));
  assert.ok(problems.some((line) => line.includes("words")));
  assert.ok(problems.some((line) => line.includes("DeckBlock")));
  assert.ok(problems.some((line) => line.includes("Fan Content")));
});

test("a reviewed guide must name the Fan Content notice and MTGJSON", () => {
  const base = {
    data: { reviewed: true, author: "Jared Cohen", updated: "2026-11-01" },
    exampleIds: IDS,
  };
  const noNotice = reviewPost({
    ...base,
    file: "no-notice.mdx",
    body: reviewedBody().replace("<FanContentNotice />", ""),
  });
  assert.ok(noNotice.some((line) => line.includes("Fan Content")));

  const noMtgjson = reviewPost({
    ...base,
    file: "no-mtgjson.mdx",
    body: reviewedBody().replaceAll("MTGJSON", "the deck file"),
  });
  assert.ok(noMtgjson.some((line) => line.includes("MTGJSON")));
});

test("a sourced guide with a real deck id passes", () => {
  const problems = reviewPost({
    file: "ok.mdx",
    data: { reviewed: true, author: "Jared Cohen", updated: "2026-11-01" },
    body: reviewedBody(),
    exampleIds: IDS,
  });
  assert.deepEqual(problems, []);
});

test("a deck link must resolve to the example catalog", () => {
  const problems = reviewPost({
    file: "bad-link.mdx",
    data: { reviewed: true, author: "Jared Cohen", updated: "2026-11-01" },
    body: reviewedBody().replace("mono-red-burn", "made-up-deck"),
    exampleIds: IDS,
  });
  assert.ok(problems.some((line) => line.includes("made-up-deck")));
});

test("affiliate disclosure is required only when an affiliate link is present", () => {
  const linked = reviewPost({
    file: "linked.mdx",
    data: { reviewed: true, author: "Jared Cohen", updated: "2026-11-01" },
    body: reviewedBody("\n\nhttps://partner.tcgplayer.com/c/123456/789012/21018?subId1=blog-example&u=deck\n"),
    exampleIds: IDS,
  });
  assert.ok(linked.some((line) => line.includes("without the disclosure")));

  const disclosed = reviewPost({
    file: "disclosed.mdx",
    data: { reviewed: true, author: "Jared Cohen", updated: "2026-11-01" },
    body: reviewedBody("\n\nBuy links may earn a commission on purchases.\n"),
    exampleIds: IDS,
  });
  assert.ok(disclosed.some((line) => line.includes("no affiliate link")));

  const both = reviewPost({
    file: "both.mdx",
    data: { reviewed: true, author: "Jared Cohen", updated: "2026-11-01" },
    body: reviewedBody("\n\nhttps://tcgplayer.pxf.io/c/1/2/3 may earn a commission.\n\nhttps://partner.tcgplayer.com/c/123456/789012/21018?subId1=blog-example&u=deck\n"),
    exampleIds: IDS,
  });
  assert.deepEqual(both, []);
});

test("formatFact matches the study-guide formatter", () => {
  assert.equal(formatFact(38, "int"), "38");
  assert.equal(formatFact(38.1, "dec1"), "38.1");
  assert.equal(formatFact(12.8, "num"), "12.8");
  assert.equal(formatFact(8, "num"), "8");
  assert.equal(formatFact(16.09, "usd"), "$16.09");
  assert.equal(formatFact(75.8, "pct"), "75.8%");
  assert.equal(formatFact(38.2, "int"), null);
});

test("a price that disagrees with the facts fixture fails", () => {
  const facts = JSON.parse(fs.readFileSync(path.join(fixtureDir, "facts.json"), "utf8"));
  const claims = JSON.parse(fs.readFileSync(path.join(fixtureDir, "bad-price.claims.json"), "utf8"));
  const body = fs.readFileSync(path.join(fixtureDir, "bad-price.mdx"), "utf8");
  const problems = claimProblems({ file: "bad-price.mdx", body, claims, facts });
  assert.ok(problems.some((line) => line.includes("$38.00")));
  assert.ok(problems.some((line) => line.includes("$9.99")));
});

test("swapping two claimed values fails even if both numbers still appear", () => {
  const facts = { summary: { lands: { median: 38 }, ramp: { median: 10 } } };
  const claims = [
    { text: "38", path: "summary.lands.median", as: "int", context: "The median is 38 lands and 10 ramp cards." },
    { text: "10", path: "summary.ramp.median", as: "int", context: "The median is 38 lands and 10 ramp cards." },
  ];
  const swapped = claimProblems({
    file: "swap.mdx",
    body: "The median is 10 lands and 38 ramp cards.",
    claims,
    facts,
  });
  assert.ok(swapped.some((line) => line.includes("not tied") || line.includes("not in the claims")));
});

test("a spelled-out number must match a claim", () => {
  const problems = claimProblems({
    file: "spelled.mdx",
    body: "Seedborn Muse is in four products.",
    claims: [{ text: "four", path: "summary.lands.median", as: "words", context: "Seedborn Muse is in four products." }],
    facts: { summary: { lands: { median: 4 } } },
  });
  assert.deepEqual(problems, []);

  const wrong = claimProblems({
    file: "spelled-bad.mdx",
    body: "Seedborn Muse is in forty-one products.",
    claims: [{ text: "four", path: "summary.lands.median", as: "words", context: "Seedborn Muse is in four products." }],
    facts: { summary: { lands: { median: 4 } } },
  });
  assert.ok(wrong.some((line) => line.includes("forty-one") || line.includes("not tied")));
});

test("changing the ramp guide to unsourced numbers fails", () => {
  const catalog = JSON.parse(fs.readFileSync(path.join(root, "src/data/example-decks.json"), "utf8"));
  const raw = fs.readFileSync(path.join(root, "content/blog/mtg-ramp-deck-guide.mdx"), "utf8");
  const body = raw
    .split("---")
    .slice(2)
    .join("---")
    .replace(/\$\d+\.\d{2}/, "$1.89")
    .replace(/\d+\.\d+%/, "62.5%")
    .replace(/(\d+) lands/, "33 lands");
  const problems = legacyClaimProblems({ file: "mtg-ramp-deck-guide.mdx", body, catalog });
  assert.ok(problems.some((line) => line.includes("$1.89")));
  assert.ok(problems.some((line) => line.includes("62.5%")));
  assert.ok(problems.some((line) => line.includes("33")));
});

test("a literal count with no claim fails", () => {
  const problems = claimProblems({
    file: "extra.mdx",
    body: "The sample is 182 lists and also 7 mystery copies.",
    claims: [{ text: "182", path: "summary.lands.median", as: "int" }],
    facts: { summary: { lands: { median: 182 } } },
  });
  assert.ok(problems.some((line) => line.includes("7")));
});

test("a near-copy fixture fails the similarity gate and a different guide does not", () => {
  const copy = fs.readFileSync(path.join(fixtureDir, "near-copy-a.mdx"), "utf8");
  const same = fs.readFileSync(path.join(fixtureDir, "near-copy-b.mdx"), "utf8");
  const problems = similarityProblems(
    [
      { file: "near-copy-a.mdx", body: copy },
      { file: "near-copy-b.mdx", body: same },
    ],
    0.45,
  );
  assert.equal(problems.length, 1);

  const distinct = similarityProblems(
    [
      { file: "near-copy-a.mdx", body: copy },
      {
        file: "other.mdx",
        body: "Pioneer challenger products are sixty card lists with a sideboard and a legality note from the bulk file.",
      },
    ],
    0.45,
  );
  assert.deepEqual(distinct, []);
});

function frontmatter(raw) {
  const parts = raw.split("---");
  const data = {};
  for (const line of parts[1].split("\n")) {
    const match = line.match(/^([A-Za-z]+):\s*(.*)$/);
    if (!match) continue;
    let value = match[2].trim();
    if (value.startsWith('"') && value.endsWith('"')) value = value.slice(1, -1);
    data[match[1]] = value;
  }
  return { title: data.title ?? "", description: data.description ?? "", body: parts.slice(2).join("---") };
}

test("a wrong land count in the ramp guide description fails", () => {
  const catalog = JSON.parse(fs.readFileSync(path.join(root, "src/data/example-decks.json"), "utf8"));
  const raw = fs.readFileSync(path.join(root, "content/blog/mtg-ramp-deck-guide.mdx"), "utf8");
  const parsed = frontmatter(raw);
  const problems = legacyHeadlineProblems({
    file: "mtg-ramp-deck-guide.mdx",
    title: parsed.title,
    description: parsed.description.replace("37 lands", "33 lands"),
    body: parsed.body,
    catalog,
  });
  assert.ok(problems.some((line) => line.includes("33") && line.includes("title or description")));
});

test("a wrong land count in the census description fails", () => {
  const facts = JSON.parse(fs.readFileSync(path.join(root, "src/data/precon_facts.json"), "utf8"));
  const raw = fs.readFileSync(path.join(root, "content/blog/precon-lands-ramp-draw.mdx"), "utf8");
  const claims = JSON.parse(fs.readFileSync(path.join(root, "content/blog/precon-lands-ramp-draw.claims.json"), "utf8"));
  const parsed = frontmatter(raw);
  const problems = headlineLiteralProblems({
    file: "precon-lands-ramp-draw.mdx",
    title: parsed.title,
    description: parsed.description.replace("plays 38 lands", "plays 33 lands"),
    claims,
    facts,
  });
  assert.ok(problems.some((line) => line.includes("33") && line.includes("title or description")));
});

test("a card claimed in the wrong deck fails", () => {
  const decks = [
    { name: "Arcane Maelstrom", cards: ["Crop Rotation", "Kalamax, the Stormsire"] },
    { name: "Timey-Wimey", cards: ["Farewell"] },
  ];
  const wrong = cardDeckProblems({
    file: "membership.mdx",
    text: "Farewell is in Arcane Maelstrom.",
    decks,
  });
  assert.ok(wrong.some((line) => line.includes("Farewell is not in Arcane Maelstrom")));
  const right = cardDeckProblems({
    file: "membership.mdx",
    text: "Farewell is in Timey-Wimey. Arcane Maelstrom's Game Changer is Crop Rotation.",
    decks,
  });
  assert.deepEqual(right, []);
});

test("a number from a different fact is not bound to the wrong subject", () => {
  const body = [
    "The high end is Tricky Terrain at 44 lands.",
    "Heads I Win, Tails You Lose is the expensive end at $266.03.",
    "Land's Wrath plays 44 removal spells and costs $266.03.",
  ].join("\n");
  const problems = claimProblems({
    file: "swap.mdx",
    body,
    claims: [
      { text: "44", path: "summary.lands.max", as: "int", context: "The high end is Tricky Terrain at 44 lands." },
      { text: "$266.03", path: "summary.price.high", as: "usd", context: "Heads I Win, Tails You Lose is the expensive end at $266.03." },
    ],
    facts: {
      summary: { lands: { max: 44 }, price: { high: 266.03 } },
      decks: {
        wrath: { name: "Land's Wrath" },
        terrain: { name: "Tricky Terrain" },
        heads: { name: "Heads I Win, Tails You Lose" },
      },
    },
  });
  assert.ok(problems.some((line) => line.includes("44") && line.includes("not bound")));
  assert.ok(problems.some((line) => line.includes("$266.03") && line.includes("not bound")));
});

test("link text, alt text, and code are checked, and the URL is not", () => {
  const problems = claimProblems({
    file: "link.mdx",
    body: "The sample is 182 lists.\n[deck that costs $999 and plays 99 lands](/blog/sideboarding-101)\n`also $7`",
    claims: [{ text: "182", path: "summary.lands.median", as: "int", context: "The sample is 182 lists." }],
    facts: { summary: { lands: { median: 182 } } },
  });
  assert.ok(problems.some((line) => line.includes("$999")));
  assert.ok(problems.some((line) => line.includes("99")));
  assert.ok(problems.some((line) => line.includes("$7")));
  assert.ok(!problems.some((line) => line.includes("101")));
});

test("fullwidth digits, ordinals, multiples, and a dozen count as literals", () => {
  const found = extractLiterals("Finished ３３rd, ran 12x, and drew a dozen.");
  assert.ok(found.counts.includes("33"));
  assert.ok(found.counts.includes("12"));
  const problems = claimProblems({
    file: "dozen.mdx",
    body: "The sample drew a dozen.",
    claims: [{ text: "1", path: "summary.lands.median", as: "int", context: "The sample drew a dozen." }],
    facts: { summary: { lands: { median: 1 } } },
  });
  assert.ok(problems.some((line) => line.includes("12")));
});

test("card membership is case-insensitive and covers more verbs", () => {
  const decks = [
    { name: "Arcane Maelstrom", cards: ["Crop Rotation"] },
    { name: "Timey-Wimey", cards: ["Farewell"] },
    { name: "Veloci-Ramp-Tor", cards: ["Cultivate"] },
    { name: "Timeless Wisdom", cards: ["Fierce Guardianship"] },
  ];
  const wrong = cardDeckProblems({
    file: "membership.mdx",
    text: "FAREWELL APPEARS IN ARCANE MAELSTROM. Veloci-Ramp-Tor runs Fierce Guardianship.",
    decks,
  });
  assert.ok(wrong.some((line) => line.includes("Farewell is not in Arcane Maelstrom")));
  assert.ok(wrong.some((line) => line.includes("Fierce Guardianship is not in Veloci-Ramp-Tor")));
  const played = cardDeckProblems({
    file: "membership.mdx",
    text: "Veloci-Ramp-Tor plays Cultivate. Timey-Wimey has Farewell.",
    decks,
  });
  assert.deepEqual(played, []);
});

test("an aggregate sentence does not inherit a different fact's metric", () => {
  const body = [
    "This census starts from 182 Commander products.",
    "The median is 38 lands, 10 ramp cards, and 10 draw cards.",
    "Most decks run 182 lands.",
    "The median precon plays 10 lands.",
  ].join("\n");
  const problems = claimProblems({
    file: "aggregate.mdx",
    body,
    claims: [
      { text: "182", path: "summary.commander_products", as: "int", context: "This census starts from 182 Commander products." },
      { text: "38", path: "summary.lands.median", as: "int", context: "The median is 38 lands, 10 ramp cards, and 10 draw cards." },
      { text: "10", path: "summary.ramp.median", as: "int", context: "The median is 38 lands, 10 ramp cards, and 10 draw cards." },
      { text: "10", path: "summary.draw.median", as: "int", context: "The median is 38 lands, 10 ramp cards, and 10 draw cards." },
    ],
    facts: {
      summary: { commander_products: 182, lands: { median: 38 }, ramp: { median: 10 }, draw: { median: 10 } },
    },
  });
  assert.ok(problems.some((line) => line.includes("182") && line.includes("not bound")));
  assert.ok(problems.some((line) => line.includes("10") && line.includes("not bound")));
  assert.ok(!problems.some((line) => line.includes("38") && line.includes("not bound")));
});

test("templated set guides share an outline and reviewed guides do not", () => {
  const read = (name) => fs.readFileSync(path.join(root, "content/blog", name), "utf8").split("---").slice(2).join("---");
  const problems = similarityProblems([
    { file: "adventures-in-the-forgotten-realms-mtg-set-guide.mdx", body: read("adventures-in-the-forgotten-realms-mtg-set-guide.mdx") },
    { file: "alara-reborn-mtg-set-guide.mdx", body: read("alara-reborn-mtg-set-guide.mdx") },
  ]);
  assert.ok(problems.some((line) => line.includes("outline")));
  const reviewed = ["precon-lands-ramp-draw.mdx", "pioneer-challenger-decks.mdx", "should-you-play-aggro.mdx", "mtg-ramp-deck-guide.mdx"].map(
    (file) => ({ file, body: read(file) }),
  );
  assert.deepEqual(
    similarityProblems(reviewed).filter((line) => line.includes("outline")),
    [],
  );
});

test("an unsourced legacy price fails against the example catalog", () => {
  const problems = legacyClaimProblems({
    file: "legacy.mdx",
    body: '<DeckBlock id="burn" /> The list costs $999.99 and wins 100.0% of the time.',
    catalog: { fetched_at: "2026-11-01", decks: { burn: { analysis: { total_cost_usd: 31.38, win_rate: 1 } } } },
  });
  assert.ok(problems.some((line) => line.includes("$999.99")));
  assert.ok(!problems.some((line) => line.includes("100.0%")));
});
