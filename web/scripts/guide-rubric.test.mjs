import assert from "node:assert/strict";
import test from "node:test";

import { reviewPost } from "./guide-rubric.mjs";

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
    body: reviewedBody("\n\nhttps://tcgplayer.pxf.io/c/1/2/3?u=deck\n"),
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
    body: reviewedBody("\n\nhttps://tcgplayer.pxf.io/c/1/2/3 may earn a commission.\n"),
    exampleIds: IDS,
  });
  assert.deepEqual(both, []);
});
