import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { PreconStatsTable } from "../components/precon-stats-table";
import {
  averageFromCurve,
  displayPreconName,
  filterPreconRows,
  formatAverage,
  loadPreconStats,
  median,
  preconDeckHref,
  sortPreconRows,
} from "./precon-stats";
import { PRECON_STATS_PATH } from "./precon-stats-path";
import { DESCRIPTION_MAX, TITLE_MAX, documentTitle, metaDescription } from "./seo";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "../..");

const EXPECTED = {
  "mtgjson-VelociRampTor_LCC": {
    name: "Veloci-Ramp-Tor",
    setCode: "LCC",
    releaseDate: "2023-11-17",
    commanders: ["Pantlaza, Sun-Favored"],
    colors: ["W", "R", "G"],
    landCount: 39,
    curve: [0, 3, 9, 17, 9, 9, 6, 7],
    average: "3.97",
    rampCount: 14,
    drawCount: 7,
    removalCount: 9,
    gameChangers: [] as string[],
    priceUsd: 107.34,
    pricePartial: false,
  },
  "mtgjson-ExitFromExile_CLB": {
    name: "Exit from Exile",
    setCode: "CLB",
    releaseDate: "2022-06-10",
    commanders: ["Faldorn, Dread Wolf Herald"],
    colors: ["R", "G"],
    landCount: 39,
    curve: [0, 1, 9, 17, 12, 7, 6, 8],
    average: "4.08",
    rampCount: 15,
    drawCount: 7,
    removalCount: 6,
    gameChangers: ["Jeska's Will"],
    priceUsd: 131.73,
    pricePartial: false,
  },
  "mtgjson-EldraziUnbound_CMM": {
    name: "Eldrazi Unbound",
    setCode: "CMM",
    releaseDate: "2023-08-04",
    commanders: ["Zhulodok, Void Gorger"],
    colors: [] as string[],
    landCount: 38,
    curve: [5, 1, 11, 10, 9, 2, 8, 15],
    average: "4.13",
    rampCount: 15,
    drawCount: 10,
    removalCount: 11,
    gameChangers: [] as string[],
    priceUsd: 239.72,
    pricePartial: false,
  },
} as const;

test("the table has one row per commander product and every row has lands and a curve", () => {
  const stats = loadPreconStats();
  const facts = JSON.parse(fs.readFileSync(path.join(root, "src/data/precon_facts.json"), "utf8")) as {
    decks: Record<string, { format?: string }>;
    summary: { commander_products: number; commander_precons: number; pioneer_challenger: number };
  };
  const official = JSON.parse(fs.readFileSync(path.join(root, "../api/app/data/official_decks.json"), "utf8")) as {
    decks: { format?: string }[];
  };
  const factCommanders = Object.values(facts.decks).filter((deck) => deck.format === "commander").length;
  const officialCommanders = official.decks.filter((deck) => deck.format === "commander").length;
  assert.equal(stats.productCount, factCommanders);
  assert.equal(stats.productCount, officialCommanders);
  assert.equal(stats.rows.length, facts.summary.commander_products);
  assert.equal(stats.uniqueCount, facts.summary.commander_precons);
  assert.equal(stats.pioneerExcluded, facts.summary.pioneer_challenger);
  assert.equal(stats.productCount, stats.uniqueCount + stats.reprintCount);
  assert.ok(stats.rows.length > 0);
  for (const row of stats.rows) {
    assert.equal(Number.isInteger(row.landCount), true, row.id);
    assert.ok(row.landCount > 0, row.id);
    assert.equal(row.curve.length, 8, row.id);
    assert.equal(row.curve.reduce((sum, count) => sum + count, 0), row.nonlandCount, row.id);
    assert.equal(row.averageManaValue, averageFromCurve(row.curve), row.id);
    assert.equal(Number.isFinite(row.averageManaValue), true, row.id);
    assert.equal(row.href, null, row.id);
    assert.equal(preconDeckHref(row.id), null);
  }
  const dates = stats.rows.map((row) => row.releaseDate);
  const sorted = [...dates].sort((left, right) => (left < right ? 1 : left > right ? -1 : 0));
  assert.deepEqual(dates, sorted);
});

test("known decks match the facts curve and the official set code", () => {
  const stats = loadPreconStats();
  const facts = JSON.parse(fs.readFileSync(path.join(root, "src/data/precon_facts.json"), "utf8")) as {
    decks: Record<string, { mana_curve: { card_count: number }[]; land_count: number; ramp_count: number; price_usd: number }>;
  };
  for (const [id, expected] of Object.entries(EXPECTED)) {
    const row = stats.rows.find((candidate) => candidate.id === id);
    assert.ok(row, id);
    const source = facts.decks[id];
    assert.deepEqual(row.curve, source.mana_curve.map((point) => point.card_count));
    assert.deepEqual(row.curve, [...expected.curve]);
    assert.equal(formatAverage(row.averageManaValue), expected.average);
    assert.equal(row.name, expected.name);
    assert.equal(row.setCode, expected.setCode);
    assert.equal(row.releaseDate, expected.releaseDate);
    assert.deepEqual(row.commanders, [...expected.commanders]);
    assert.deepEqual(row.colors, [...expected.colors]);
    assert.equal(row.landCount, expected.landCount);
    assert.equal(row.landCount, source.land_count);
    assert.equal(row.rampCount, expected.rampCount);
    assert.equal(row.rampCount, source.ramp_count);
    assert.equal(row.drawCount, expected.drawCount);
    assert.equal(row.removalCount, expected.removalCount);
    assert.deepEqual(row.gameChangers, [...expected.gameChangers]);
    assert.equal(row.gameChangerCount, expected.gameChangers.length);
    assert.equal(row.priceUsd, expected.priceUsd);
    assert.equal(row.priceUsd, source.price_usd);
    assert.equal(row.pricePartial, expected.pricePartial);
  }
});

test("medians are the middle of the same rows the table shows", () => {
  const stats = loadPreconStats();
  assert.equal(median([10, 10, 30, 20]), 15);
  assert.equal(stats.all.decks, stats.productCount);
  assert.equal(stats.all.land, 38);
  assert.equal(stats.all.averageManaValue, 3.62);
  assert.equal(stats.all.ramp, 10);
  assert.equal(stats.all.draw, 10);
  assert.equal(stats.all.removal, 7);
  assert.equal(stats.all.gameChangers, 0);
  assert.equal(stats.all.price, 75.53);
  assert.equal(stats.all.pricedDecks, 163);
  assert.equal(stats.unique.decks, 174);
  assert.equal(stats.unique.land, 38);
  assert.equal(stats.unique.averageManaValue, 3.61);
  assert.equal(stats.unique.price, 75.41);
  assert.equal(stats.unique.pricedDecks, 156);
  const year2016 = stats.byYear.find((row) => row.year === 2016);
  assert.ok(year2016);
  assert.equal(year2016.price, null);
  assert.equal(year2016.pricedDecks, 0);
  assert.equal(stats.byRange.reduce((sum, row) => sum + row.decks, 0), stats.productCount);
  assert.equal(stats.sources.priceDate, "2026-11-01");
  assert.equal(stats.sources.priceField, "prices.usd");
});

test("color and set filters keep the matching decks", () => {
  const rows = loadPreconStats().rows;
  const greenWhite = filterPreconRows(rows, { colors: ["G", "W"], colorless: false, setCode: "" });
  assert.ok(greenWhite.some((row) => row.id === "mtgjson-VelociRampTor_LCC"));
  assert.equal(greenWhite.some((row) => row.id === "mtgjson-EldraziUnbound_CMM"), false);
  assert.ok(greenWhite.every((row) => row.colors.includes("G") && row.colors.includes("W")));
  const colorless = filterPreconRows(rows, { colors: [], colorless: true, setCode: "" });
  assert.ok(colorless.some((row) => row.id === "mtgjson-EldraziUnbound_CMM"));
  assert.ok(colorless.every((row) => row.colors.length === 0));
  const lostCaverns = filterPreconRows(rows, { colors: [], colorless: false, setCode: "LCC" });
  assert.ok(lostCaverns.every((row) => row.setCode === "LCC"));
  assert.ok(lostCaverns.some((row) => row.name === "Veloci-Ramp-Tor"));
  const byLands = sortPreconRows(rows, "landCount", "asc");
  assert.ok(byLands[0].landCount <= byLands[1].landCount);
});

test("the server table markup contains the deck rows before any click", () => {
  const stats = loadPreconStats();
  const html = renderToStaticMarkup(
    createElement(PreconStatsTable, { rows: stats.rows, sets: stats.sets, priceDate: stats.sources.priceDate }),
  );
  assert.match(html, /Veloci-Ramp-Tor/);
  assert.match(html, /Pantlaza, Sun-Favored/);
  assert.match(html, />39</);
  assert.match(html, /3\.97/);
  assert.match(html, /Exit from Exile/);
  assert.match(html, /Jeska&#x27;s Will|Jeska's Will/);
  assert.match(html, /Eldrazi Unbound/);
  assert.match(html, /Zhulodok, Void Gorger/);
  assert.match(html, /2026-11-01/);
  assert.equal(html.includes('href="/commander-precons/'), false);
  assert.match(html, new RegExp(`Showing ${stats.productCount} of ${stats.productCount}`));
});

test("deck names show short words in lower case after the first word", () => {
  assert.equal(displayPreconName("Guided By Nature"), "Guided by Nature");
  assert.equal(displayPreconName("Forged In Stone"), "Forged in Stone");
  assert.equal(displayPreconName("From Cute to Brute"), "From Cute to Brute");
  assert.equal(displayPreconName("The Hosts of Mordor"), "The Hosts of Mordor");
  assert.equal(displayPreconName("Angels: They're Just Like Us but Cooler and with Wings"), "Angels: They're Just Like Us but Cooler and with Wings");
  assert.equal(displayPreconName("Heroes: The Next Wave"), "Heroes: The Next Wave");
  const rows = loadPreconStats().rows;
  for (const row of rows) {
    assert.equal(row.name, displayPreconName(row.name), row.id);
    if (row.reprintOfName) assert.equal(row.reprintOfName, displayPreconName(row.reprintOfName), row.id);
  }
  for (const name of ["Built from Scratch", "Forged in Stone", "Guided by Nature", "Sworn to Darkness"]) {
    assert.ok(rows.some((row) => row.name === name), name);
  }
  assert.equal(rows.some((row) => row.name === "Guided By Nature"), false);
});

test("the table labels the color filter and shows Game Changer names", () => {
  const stats = loadPreconStats();
  const html = renderToStaticMarkup(
    createElement(PreconStatsTable, { rows: stats.rows, sets: stats.sets, priceDate: stats.sources.priceDate }),
  );
  assert.match(html, /<legend class="label">Includes colors<\/legend>/);
  assert.match(html, /<span class="precon-gc-names">Jeska(&#x27;|')s Will<\/span>/);
  assert.equal(/class="sr-only">: Jeska/.test(html), false);
});

test("the stats page is in the sitemap and stays off the ad slots", () => {
  const sitemap = fs.readFileSync(path.join(root, "src/app/sitemap.ts"), "utf8");
  const page = fs.readFileSync(path.join(root, "src/app/commander-precons/stats/page.tsx"), "utf8");
  assert.match(sitemap, /PRECON_STATS_PATH/);
  assert.equal(PRECON_STATS_PATH, "/commander-precons/stats");
  assert.doesNotMatch(page, /EnableAds/);
  const title = documentTitle("Commander precon stats");
  assert.ok(title.length <= TITLE_MAX, title);
  const stats = loadPreconStats();
  const description = metaDescription(
    `Land count, mana curve, ramp, draw, removal, Game Changers, and Scryfall prices for ${stats.productCount} official Commander precons. Price snapshot ${stats.sources.priceDate}.`,
  );
  assert.ok(description.length <= DESCRIPTION_MAX, description);
});
