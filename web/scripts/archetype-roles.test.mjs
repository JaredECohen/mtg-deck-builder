import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { isOneShotPump, isStaticAnthem, protectsAnotherCreature, roleCounts, storedRolesMatch } from "./archetype-roles.mjs";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const data = path.join(root, "src", "data");

test("stored role counts match the oracle text and the precon ramp lists", () => {
  const oracle = JSON.parse(fs.readFileSync(path.join(data, "example-card-oracle.json"), "utf8")).cards;
  const decks = JSON.parse(fs.readFileSync(path.join(data, "example-decks.json"), "utf8")).decks;
  const facts = JSON.parse(fs.readFileSync(path.join(data, "precon_facts.json"), "utf8"));
  const { roles } = roleCounts(oracle, decks, facts);
  assert.deepEqual(storedRolesMatch(decks, roles), []);
});

test("protection, anthems, and Dig Through Time stay pinned to the oracle text", () => {
  const oracle = JSON.parse(fs.readFileSync(path.join(data, "example-card-oracle.json"), "utf8")).cards;
  const decks = JSON.parse(fs.readFileSync(path.join(data, "example-decks.json"), "utf8")).decks;
  const facts = JSON.parse(fs.readFileSync(path.join(data, "precon_facts.json"), "utf8"));
  assert.equal(oracle["Dig Through Time"].cmc, 8);
  assert.equal(protectsAnotherCreature(oracle["Stonecoil Serpent"].oracle_text), false);
  assert.equal(protectsAnotherCreature(oracle["Paradise Druid"].oracle_text), false);
  assert.equal(protectsAnotherCreature(oracle["Alseid of Life's Bounty"].oracle_text), true);
  assert.equal(isStaticAnthem(oracle.Overrun.oracle_text), false);
  assert.equal(isOneShotPump(oracle.Overrun.oracle_text), true);
  assert.equal(isStaticAnthem(oracle["Dictate of Heliod"].oracle_text), true);
  assert.equal(isStaticAnthem(oracle["Jor Kadeen, the Prevailer"].oracle_text), false);
  const { roles, notes } = roleCounts(oracle, decks, facts);
  assert.equal(roles["lotus-field"].dig_mv, 8);
  assert.equal(roles["orzhov-auras"].protection_count, 11);
  assert.equal(roles["virtue-and-valor"].protection_count, 2);
  assert.equal(notes["orzhov-auras"].shields.some((name) => name.includes("Stonecoil")), false);
  assert.equal(notes["token-triumph"].staticAnthems.some((name) => name.includes("Overrun")), false);
  assert.equal(roles["token-triumph"].static_anthems, 5);
  assert.equal(roles["rebellion-rising"].static_anthems, 3);
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
