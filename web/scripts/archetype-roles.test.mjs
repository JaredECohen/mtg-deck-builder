import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { roleCounts, storedRolesMatch } from "./archetype-roles.mjs";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const data = path.join(root, "src", "data");

test("stored role counts match the oracle text and the precon ramp lists", () => {
  const oracle = JSON.parse(fs.readFileSync(path.join(data, "example-card-oracle.json"), "utf8")).cards;
  const decks = JSON.parse(fs.readFileSync(path.join(data, "example-decks.json"), "utf8")).decks;
  const facts = JSON.parse(fs.readFileSync(path.join(data, "precon_facts.json"), "utf8"));
  const { roles } = roleCounts(oracle, decks, facts);
  assert.deepEqual(storedRolesMatch(decks, roles), []);
});

test("the rubric check exits non-zero on a fixture guide that breaks the gates", () => {
  const result = spawnSync(
    process.execPath,
    ["scripts/check-guide-rubric.mjs", "--fixture", "scripts/fixtures/guide-rubric/broken-gate.mdx"],
    { cwd: root, encoding: "utf8" },
  );
  assert.notEqual(result.status, 0);
  const output = `${result.stdout}\n${result.stderr}`;
  assert.match(output, /words/);
  assert.match(output, /table|DeckBlock/);
});
