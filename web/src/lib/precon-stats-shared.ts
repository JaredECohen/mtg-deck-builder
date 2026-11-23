/**
 * Pure helpers for the precon stats table. No filesystem access, so a client
 * component can import this without pulling the facts file into the browser.
 */

export const COLOR_ORDER = ["W", "U", "B", "R", "G"] as const;

export const COLOR_LABELS: Record<(typeof COLOR_ORDER)[number], string> = {
  W: "White",
  U: "Blue",
  B: "Black",
  R: "Red",
  G: "Green",
};

/** Release-year buckets. The label is the year span, not a design era. */
export const PRECON_YEAR_RANGES = [
  { label: "2011–2016", from: 2011, to: 2016 },
  { label: "2017–2020", from: 2017, to: 2020 },
  { label: "2021–2023", from: 2021, to: 2023 },
  { label: "2024–2026", from: 2024, to: 2026 },
] as const;

export type PreconSortKey =
  | "name"
  | "setCode"
  | "releaseDate"
  | "colors"
  | "commanders"
  | "landCount"
  | "averageManaValue"
  | "curve"
  | "rampCount"
  | "drawCount"
  | "removalCount"
  | "gameChangerCount"
  | "priceUsd";

export type SortDirection = "asc" | "desc";

export type PreconStatsRow = {
  id: string;
  name: string;
  setCode: string;
  releaseDate: string;
  year: number;
  colors: string[];
  commanders: string[];
  landCount: number;
  nonlandCount: number;
  /** Quantity-weighted mean of the stored curve. Bucket 7 counts as 7. */
  averageManaValue: number;
  curve: number[];
  rampCount: number;
  drawCount: number;
  removalCount: number;
  gameChangerCount: number;
  gameChangers: string[];
  priceUsd: number;
  pricePartial: boolean;
  unpricedCount: number;
  foilCommanders: string[];
  isReprint: boolean;
  reprintOfName: string | null;
  reprintOfRelease: string | null;
  /** Site path of a per-product page, or null when that page does not exist. */
  href: string | null;
};

export type PreconMedians = {
  decks: number;
  land: number;
  averageManaValue: number;
  ramp: number;
  draw: number;
  removal: number;
  gameChangers: number;
  price: number | null;
  pricedDecks: number;
};

export type PreconYearMedians = PreconMedians & { year: number };
export type PreconRangeMedians = PreconMedians & { label: string };

export type PreconStatsSources = {
  fetchedAt: string;
  decksName: string;
  decksSnapshot: string;
  decksLicense: string;
  oracleName: string;
  oracleUrl: string;
  oracleUpdatedAt: string;
  priceName: string;
  priceUrl: string;
  priceUpdatedAt: string;
  priceDate: string;
  priceField: string;
  priceNote: string;
  gameChangersAsOf: string;
  gameChangerListSize: number;
};

export type PreconSetOption = { code: string; decks: number };

export type PreconStatsModel = {
  rows: PreconStatsRow[];
  productCount: number;
  uniqueCount: number;
  reprintCount: number;
  pioneerExcluded: number;
  decksWithSideboard: number;
  gameChangerCopiesMatch: boolean;
  sources: PreconStatsSources;
  all: PreconMedians;
  unique: PreconMedians;
  byYear: PreconYearMedians[];
  byRange: PreconRangeMedians[];
  sets: PreconSetOption[];
};

export type PreconFilter = {
  colors: string[];
  colorless: boolean;
  setCode: string;
};

export const EMPTY_PRECON_FILTER: PreconFilter = { colors: [], colorless: false, setCode: "" };

const DEFAULT_DIRECTION: Record<PreconSortKey, SortDirection> = {
  name: "asc",
  setCode: "asc",
  releaseDate: "desc",
  colors: "asc",
  commanders: "asc",
  landCount: "desc",
  averageManaValue: "desc",
  curve: "asc",
  rampCount: "desc",
  drawCount: "desc",
  removalCount: "desc",
  gameChangerCount: "desc",
  priceUsd: "desc",
};

export function defaultSortDirection(key: PreconSortKey): SortDirection {
  return DEFAULT_DIRECTION[key];
}

export function median(values: number[]): number {
  if (!values.length) throw new Error("median needs at least one value");
  const sorted = [...values].sort((left, right) => left - right);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[mid];
  return (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Half away from zero. Count and mana-value medians use this. */
export function roundTo(value: number, digits: number): number {
  const factor = 10 ** digits;
  return (Math.sign(value) * Math.round(Math.abs(value) * factor)) / factor;
}

/** Median of dollar amounts that are already cents, rounded to a cent. */
export function medianPrice(values: number[]): number {
  const cents = values.map((value) => Math.round(value * 100)).sort((left, right) => left - right);
  const mid = Math.floor(cents.length / 2);
  const medianCents = cents.length % 2 === 1 ? cents[mid] : (cents[mid - 1] + cents[mid]) / 2;
  return Math.round(medianCents) / 100;
}

export function averageFromCurve(curve: number[]): number {
  const cards = curve.reduce((sum, count) => sum + count, 0);
  if (cards <= 0) throw new Error("curve has no nonland cards");
  const total = curve.reduce((sum, count, manaValue) => sum + manaValue * count, 0);
  return total / cards;
}

// MTGJSON capitalizes some short words in deck names ("Guided By Nature", "Forged In Stone"),
// while other entries for the same product use title case ("Guided by Nature"). Lowercase these
// words unless they open the name or follow a colon, so the table shows one spelling.
const MINOR_WORDS = new Set(["a", "an", "and", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with"]);

export function displayPreconName(name: string): string {
  const words = name.split(" ");
  return words
    .map((word, index) => {
      if (index === 0 || words[index - 1].endsWith(":")) return word;
      return MINOR_WORDS.has(word.toLowerCase()) ? word.toLowerCase() : word;
    })
    .join(" ");
}

export function formatAverage(value: number): string {
  return value.toFixed(2);
}

export function formatCountMedian(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

export function formatMoney(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function mediansFor(rows: PreconStatsRow[]): PreconMedians {
  if (!rows.length) throw new Error("median group is empty");
  const priced = rows.filter((row) => !row.pricePartial).map((row) => row.priceUsd);
  return {
    decks: rows.length,
    land: roundTo(median(rows.map((row) => row.landCount)), 1),
    averageManaValue: roundTo(median(rows.map((row) => row.averageManaValue)), 2),
    ramp: roundTo(median(rows.map((row) => row.rampCount)), 1),
    draw: roundTo(median(rows.map((row) => row.drawCount)), 1),
    removal: roundTo(median(rows.map((row) => row.removalCount)), 1),
    gameChangers: roundTo(median(rows.map((row) => row.gameChangerCount)), 1),
    price: priced.length ? medianPrice(priced) : null,
    pricedDecks: priced.length,
  };
}

function compareKey(left: PreconStatsRow, right: PreconStatsRow, key: PreconSortKey): number {
  switch (key) {
    case "name":
      return left.name.localeCompare(right.name, "en");
    case "setCode":
      return left.setCode.localeCompare(right.setCode, "en");
    case "releaseDate":
      return left.releaseDate.localeCompare(right.releaseDate);
    case "colors":
      return (left.colors.join("") || "C").localeCompare(right.colors.join("") || "C");
    case "commanders":
      return left.commanders.join(", ").localeCompare(right.commanders.join(", "), "en");
    case "landCount":
      return left.landCount - right.landCount;
    case "averageManaValue":
      return left.averageManaValue - right.averageManaValue;
    case "curve":
      for (let index = 0; index < left.curve.length; index += 1) {
        const diff = left.curve[index] - right.curve[index];
        if (diff !== 0) return diff;
      }
      return 0;
    case "rampCount":
      return left.rampCount - right.rampCount;
    case "drawCount":
      return left.drawCount - right.drawCount;
    case "removalCount":
      return left.removalCount - right.removalCount;
    case "gameChangerCount":
      return left.gameChangerCount - right.gameChangerCount;
    case "priceUsd":
      return left.priceUsd - right.priceUsd;
    default:
      return 0;
  }
}

export function sortPreconRows(rows: PreconStatsRow[], key: PreconSortKey, direction: SortDirection): PreconStatsRow[] {
  const sign = direction === "asc" ? 1 : -1;
  return [...rows].sort((left, right) => {
    const primary = compareKey(left, right, key);
    if (primary !== 0) return primary * sign;
    const name = left.name.localeCompare(right.name, "en");
    if (name !== 0) return name;
    return left.id.localeCompare(right.id);
  });
}

export function filterPreconRows(rows: PreconStatsRow[], filter: PreconFilter): PreconStatsRow[] {
  return rows.filter((row) => {
    if (filter.setCode && row.setCode !== filter.setCode) return false;
    if (filter.colorless) return row.colors.length === 0;
    if (!filter.colors.length) return true;
    return filter.colors.every((color) => row.colors.includes(color));
  });
}
