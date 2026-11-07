import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import matter from "gray-matter";

import { DESCRIPTION_MAX, TITLE_MAX, documentTitle, metaDescription, socialTitle } from "./seo";

const blogDir = path.join(path.dirname(fileURLToPath(import.meta.url)), "../../content/blog");

test("document titles keep the site name only when it fits", () => {
  assert.equal(documentTitle("Should You Play an Aggro Deck in MTG?"), "Should You Play an Aggro Deck in MTG? | MTG Deck Lab");
  const long = "How Many Lands, Ramp, and Draw Spells Do Commander Precons Play?";
  const titled = documentTitle(long);
  assert.ok(titled.length <= TITLE_MAX, titled);
  assert.equal(titled.includes("| MTG Deck Lab"), false);
  assert.equal(socialTitle(long).length <= TITLE_MAX, true);
});

test("meta descriptions stop at a sentence inside the limit", () => {
  const tempo =
    "What does a tempo deck give up in Magic: The Gathering? Spirits goldfishes turn 6.62 for $22.40. Phoenix is turn 9.78, and Expressive Iteration is not Pioneer-legal.";
  const trimmed = metaDescription(tempo);
  assert.ok(trimmed.length <= DESCRIPTION_MAX, `${trimmed.length}: ${trimmed}`);
  assert.match(trimmed, /\$22\.40\.$/);
  assert.equal(metaDescription("Short description.").length <= DESCRIPTION_MAX, true);
});

test("every guide's metadata title and description fit the limits", () => {
  const files = fs.readdirSync(blogDir).filter((file) => file.endsWith(".mdx"));
  assert.ok(files.length > 0);
  for (const file of files) {
    const { data } = matter(fs.readFileSync(path.join(blogDir, file), "utf8"));
    if (data.draft === true || data.archived === true) continue;
    const title = documentTitle(String(data.title ?? ""));
    const description = metaDescription(String(data.description ?? ""));
    assert.ok(title.length <= TITLE_MAX, `${file} title ${title.length}: ${title}`);
    assert.ok(description.length <= DESCRIPTION_MAX, `${file} description ${description.length}`);
    assert.equal(socialTitle(String(data.title ?? "")).length <= TITLE_MAX, true);
  }
});
