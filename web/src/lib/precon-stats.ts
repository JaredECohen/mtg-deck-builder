import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import {
  COLOR_ORDER,
  PRECON_YEAR_RANGES,
  averageFromCurve,
  displayPreconName,
  mediansFor,
  sortPreconRows,
  type PreconStatsModel,
  type PreconStatsRow,
  type PreconStatsSources,
} from "./precon-stats-shared";

export {
  COLOR_ORDER,
  PRECON_YEAR_RANGES,
  averageFromCurve,
  defaultSortDirection,
  displayPreconName,
  filterPreconRows,
  formatAverage,
  formatCountMedian,
  formatMoney,
  median,
  medianPrice,
  roundTo,
  sortPreconRows,
} from "./precon-stats-shared";
export type {
  PreconFilter,
  PreconMedians,
  PreconRangeMedians,
  PreconSetOption,
  PreconSortKey,
  PreconStatsModel,
  PreconStatsRow,
  PreconStatsSources,
  PreconYearMedians,
  SortDirection,
} from "./precon-stats-shared";

/**
 * Commander precon table built from the committed facts file and the MTGJSON
 * snapshot. Nothing here calls an API or a model.
 *
 * There is no per-product deck route. `preconDeckHref` stays empty so this
 * page does not create one and does not change indexability.
 */

const LIB_DIR = path.dirname(fileURLToPath(import.meta.url));

function existingPath(candidates: string[]): string {
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  throw new Error(`Missing data file. Tried: ${candidates.join(", ")}`);
}

function readJson(file: string): unknown {
  return JSON.parse(fs.readFileSync(file, "utf8")) as unknown;
}

function asRecord(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`${label} is not an object`);
  return value as Record<string, unknown>;
}

function asString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value) throw new Error(`${label} is missing`);
  return value;
}

function asNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) throw new Error(`${label} is missing`);
  return value;
}

function asStringList(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${label} is not a list of names`);
  }
  return value as string[];
}

/** No indexable per-precon page exists. Callers render the name as text. */
export function preconDeckHref(_id: string): string | null {
  return null;
}

function colorIdentity(value: unknown, label: string): string[] {
  const raw = asStringList(value, label);
  const unknown = raw.filter((color) => !COLOR_ORDER.includes(color as (typeof COLOR_ORDER)[number]));
  if (unknown.length) throw new Error(`${label} has ${unknown.join(", ")}`);
  return COLOR_ORDER.filter((color) => raw.includes(color));
}

function curveCounts(value: unknown, label: string): number[] {
  if (!Array.isArray(value) || value.length !== 8) throw new Error(`${label} curve is not 8 buckets`);
  return value.map((point, index) => {
    const row = asRecord(point, `${label} curve ${index}`);
    if (asNumber(row.mana_value, `${label} mana value`) !== index) throw new Error(`${label} curve is out of order`);
    const count = asNumber(row.card_count, `${label} curve count`);
    if (!Number.isInteger(count) || count < 0) throw new Error(`${label} curve count is invalid`);
    return count;
  });
}

function loadSources(facts: Record<string, unknown>, summary: Record<string, unknown>): PreconStatsSources {
  const sources = asRecord(facts.sources, "sources");
  const decks = asRecord(sources.decks, "deck source");
  const cards = asRecord(sources.cards, "card source");
  const prices = asRecord(sources.prices, "price source");
  const brackets = asRecord(sources.brackets, "bracket source");
  const priceUpdatedAt = asString(prices.updated_at, "price updated_at");
  return {
    fetchedAt: asString(facts.fetched_at, "fetched_at"),
    decksName: asString(decks.name, "deck source name"),
    decksSnapshot: asString(decks.snapshot, "deck snapshot"),
    decksLicense: asString(decks.license, "deck license"),
    oracleName: asString(cards.name, "oracle name"),
    oracleUrl: asString(cards.url, "oracle url"),
    oracleUpdatedAt: asString(cards.updated_at, "oracle updated_at"),
    priceName: asString(prices.name, "price name"),
    priceUrl: asString(prices.url, "price url"),
    priceUpdatedAt,
    priceDate: priceUpdatedAt.slice(0, 10),
    priceField: asString(prices.price_field, "price field"),
    priceNote: asString(prices.price_note, "price note"),
    gameChangersAsOf: asString(brackets.game_changers_as_of, "game changers as_of"),
    gameChangerListSize: asNumber(summary.game_changer_list_size, "game changer list size"),
  };
}

function buildModel(): PreconStatsModel {
  const facts = asRecord(
    readJson(
      existingPath([
        path.join(LIB_DIR, "../data/precon_facts.json"),
        path.join(process.cwd(), "src/data/precon_facts.json"),
        path.join(process.cwd(), "web/src/data/precon_facts.json"),
      ]),
    ),
    "precon facts",
  );
  const official = asRecord(
    readJson(
      existingPath([
        path.join(LIB_DIR, "../../../api/app/data/official_decks.json"),
        path.join(process.cwd(), "../api/app/data/official_decks.json"),
        path.join(process.cwd(), "api/app/data/official_decks.json"),
      ]),
    ),
    "official decks",
  );
  const summary = asRecord(facts.summary, "summary");
  const sources = loadSources(facts, summary);
  const setById = new Map<string, string>();
  const officialDecks = official.decks;
  if (!Array.isArray(officialDecks)) throw new Error("official decks list is missing");
  let officialCommanders = 0;
  for (const entry of officialDecks) {
    const deck = asRecord(entry, "official deck");
    const id = asString(deck.id, "official deck id");
    if (deck.format === "commander") {
      officialCommanders += 1;
      setById.set(id, asString(deck.set_code, `${id} set code`));
    }
  }
  const reprintOf = new Map<string, { name: string; release: string }>();
  const reprintGroups = summary.duplicate_reprints;
  if (!Array.isArray(reprintGroups)) throw new Error("duplicate reprints are missing");
  for (const entry of reprintGroups) {
    const group = asRecord(entry, "reprint group");
    const keptName = asString(group.kept_name, "reprint kept name");
    const keptRelease = asString(group.kept_release, "reprint kept release");
    const copies = group.copies;
    if (!Array.isArray(copies)) throw new Error("reprint copies are missing");
    for (const copyEntry of copies) {
      const copy = asRecord(copyEntry, "reprint copy");
      reprintOf.set(asString(copy.id, "reprint id"), { name: displayPreconName(keptName), release: keptRelease });
    }
  }
  const deckMap = asRecord(facts.decks, "decks");
  const rows: PreconStatsRow[] = [];
  let decksWithSideboard = 0;
  let gameChangerCopiesMatch = true;
  for (const [id, entry] of Object.entries(deckMap)) {
    const deck = asRecord(entry, id);
    if (deck.format !== "commander") continue;
    if (asString(deck.id, `${id} id`) !== id) throw new Error(`${id} does not match its key`);
    const curve = curveCounts(deck.mana_curve, id);
    const nonland = curve.reduce((sum, count) => sum + count, 0);
    const landCount = asNumber(deck.land_count, `${id} land count`);
    if (!Number.isInteger(landCount) || landCount < 0) throw new Error(`${id} land count is invalid`);
    if (asNumber(deck.nonland_count, `${id} nonland count`) !== nonland) {
      throw new Error(`${id} nonland count does not match the curve`);
    }
    const mainboard = asNumber(deck.mainboard_cards, `${id} mainboard`);
    const missing = asStringList(deck.missing_oracle, `${id} missing oracle`);
    if (missing.length) throw new Error(`${id} is missing oracle text`);
    if (landCount + nonland !== mainboard) throw new Error(`${id} lands plus curve do not equal the mainboard`);
    if (asNumber(deck.sideboard_cards, `${id} sideboard`) > 0) decksWithSideboard += 1;
    const gameChangers = asStringList(deck.game_changers, `${id} game changers`);
    if (asNumber(deck.game_changer_copies, `${id} game changer copies`) !== gameChangers.length) {
      gameChangerCopiesMatch = false;
    }
    const releaseDate = asString(deck.release_date, `${id} release date`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(releaseDate)) throw new Error(`${id} release date is invalid`);
    const setCode = setById.get(id);
    if (!setCode) throw new Error(`${id} has no set code in the official snapshot`);
    const reprint = reprintOf.get(id);
    const unpriced = asStringList(deck.unpriced, `${id} unpriced`);
    rows.push({
      id,
      name: displayPreconName(asString(deck.name, `${id} name`)),
      setCode,
      releaseDate,
      year: Number(releaseDate.slice(0, 4)),
      colors: colorIdentity(deck.color_identity, `${id} colors`),
      commanders: asStringList(deck.commanders, `${id} commanders`),
      landCount,
      nonlandCount: nonland,
      averageManaValue: averageFromCurve(curve),
      curve,
      rampCount: asNumber(deck.ramp_count, `${id} ramp`),
      drawCount: asNumber(deck.draw_count, `${id} draw`),
      removalCount: asNumber(deck.removal_count, `${id} removal`),
      gameChangerCount: gameChangers.length,
      gameChangers,
      priceUsd: asNumber(deck.price_usd, `${id} price`),
      pricePartial: unpriced.length > 0,
      unpricedCount: unpriced.length,
      foilCommanders: asStringList(deck.foil_priced, `${id} foil`),
      isReprint: Boolean(reprint),
      reprintOfName: reprint?.name ?? null,
      reprintOfRelease: reprint?.release ?? null,
      href: preconDeckHref(id),
    });
  }
  if (rows.length !== officialCommanders) {
    throw new Error(`facts have ${rows.length} commander decks and the snapshot has ${officialCommanders}`);
  }
  const sorted = sortPreconRows(rows, "releaseDate", "desc");
  const uniqueRows = sorted.filter((row) => !row.isReprint);
  if (uniqueRows.length + reprintOf.size !== sorted.length) throw new Error("reprint ids do not match the table");
  const byYearMap = new Map<number, PreconStatsRow[]>();
  for (const row of sorted) {
    const group = byYearMap.get(row.year) ?? [];
    group.push(row);
    byYearMap.set(row.year, group);
  }
  const byYear = [...byYearMap.keys()]
    .sort((left, right) => left - right)
    .map((year) => ({ year, ...mediansFor(byYearMap.get(year) ?? []) }));
  const byRange = PRECON_YEAR_RANGES.map((range) => {
    const group = sorted.filter((row) => row.year >= range.from && row.year <= range.to);
    if (!group.length) throw new Error(`year range ${range.label} has no decks`);
    return { label: range.label, ...mediansFor(group) };
  });
  const uncovered = sorted.filter(
    (row) => !PRECON_YEAR_RANGES.some((range) => row.year >= range.from && row.year <= range.to),
  );
  if (uncovered.length) throw new Error(`no year range covers ${uncovered[0].year}`);
  const setCounts = new Map<string, number>();
  for (const row of sorted) setCounts.set(row.setCode, (setCounts.get(row.setCode) ?? 0) + 1);
  const sets = [...setCounts.entries()]
    .map(([code, decks]) => ({ code, decks }))
    .sort((left, right) => left.code.localeCompare(right.code));
  return {
    rows: sorted,
    productCount: sorted.length,
    uniqueCount: uniqueRows.length,
    reprintCount: reprintOf.size,
    pioneerExcluded: asNumber(summary.pioneer_challenger, "pioneer count"),
    decksWithSideboard,
    gameChangerCopiesMatch,
    sources,
    all: mediansFor(sorted),
    unique: mediansFor(uniqueRows),
    byYear,
    byRange,
    sets,
  };
}

let cached: PreconStatsModel | null = null;

export function loadPreconStats(): PreconStatsModel {
  if (!cached) cached = buildModel();
  return cached;
}
