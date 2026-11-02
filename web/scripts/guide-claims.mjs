// Numeric claims and near-duplicate checks for reviewed guides.
// Prices, percentages, and counts in a claims sidecar must equal the facts
// file. Guides without a sidecar are checked against the example-deck catalog
// they cite. No model is called.

export const SIMILARITY_THRESHOLD = 0.45;
const SHINGLE = 5;

export function formatFact(value, kind) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  if (kind === "int") {
    if (Math.abs(value - Math.round(value)) > 1e-6) return null;
    return String(Math.round(value));
  }
  if (kind === "dec1") return value.toFixed(1);
  if (kind === "num") {
    if (Math.abs(value - Math.round(value)) < 1e-6) return String(Math.round(value));
    return value.toFixed(1);
  }
  if (kind === "usd") return `$${value.toFixed(2)}`;
  if (kind === "pct") return `${value.toFixed(1)}%`;
  return null;
}

function claimAppears(body, text) {
  if (text.startsWith("$") || text.endsWith("%")) return body.includes(text);
  const escaped = text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // A sentence period is a boundary. A decimal point is not, so 12.8 is not "12" or "8".
  return new RegExp(`(?<![\\d.])${escaped}(?!\\d)(?!\\.\\d)`).test(body);
}

export function factAt(root, path) {
  let current = root;
  for (const part of String(path).split(".")) {
    if (current == null || typeof current !== "object") return undefined;
    current = current[part];
  }
  return current;
}

function maskNames(text, names) {
  const ordered = [...names].filter((name) => typeof name === "string" && /\d/.test(name)).sort((a, b) => b.length - a.length);
  let masked = text;
  for (const name of ordered) masked = masked.split(name).join(" ");
  return masked;
}

export function factNames(facts, catalog) {
  const names = [];
  for (const deck of Object.values(facts?.decks ?? {})) {
    if (deck?.name) names.push(deck.name);
    for (const key of ["ramp_cards", "draw_cards", "removal_cards", "commanders", "game_changers", "unpriced", "illegal_in_format", "missing_oracle"]) {
      for (const card of deck?.[key] ?? []) names.push(typeof card === "string" ? card : card?.name);
    }
  }
  for (const row of facts?.game_changers ?? []) if (row?.name) names.push(row.name);
  for (const deck of Object.values(catalog?.decks ?? {})) {
    if (deck?.name) names.push(deck.name);
    for (const card of [...(deck?.mainboard ?? []), ...(deck?.sideboard ?? [])]) names.push(card?.name);
    for (const card of deck?.analysis?.top_cards ?? []) names.push(card?.name);
    for (const card of deck?.analysis?.unpriced ?? []) names.push(card);
    for (const card of deck?.analysis?.illegal_in_format ?? []) names.push(card);
  }
  return names.filter(Boolean);
}

export function extractLiterals(body, names = []) {
  const text = maskNames(
    String(body)
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/`[^`]*`/g, " "),
    names,
  );
  const prices = [...text.matchAll(/\$(\d+(?:\.\d+)?)/g)].map((match) => match[1]);
  const percents = [...text.matchAll(/(\d+(?:\.\d+)?)%/g)].map((match) => match[1]);
  const stripped = text
    .replace(/\$\d+(?:\.\d+)?/g, " ")
    .replace(/\d+(?:\.\d+)?%/g, " ")
    .replace(/\b\d{4}-\d{2}-\d{2}\b/g, " ");
  const counts = [...stripped.matchAll(/\b\d+(?:\.\d+)?\b/g)].map((match) => match[0]);
  return { prices, percents, counts };
}

function roundsTo(value, literal) {
  const decimals = literal.includes(".") ? literal.split(".")[1].length : 0;
  const factor = 10 ** decimals;
  const rounded = Math.round((Number(value) + Number.EPSILON) * factor) / factor;
  const formatted = decimals ? rounded.toFixed(decimals) : String(Math.round(rounded));
  return formatted === literal;
}

function collectNumbers(node, key, prices, percents, counts) {
  if (typeof node === "number" && Number.isFinite(node)) {
    if (/usd|cost|price/i.test(key)) prices.push(node);
    else if (/share|win_rate|pct/i.test(key)) percents.push(node <= 1 ? node * 100 : node);
    else counts.push(node);
    return;
  }
  if (typeof node === "string") {
    if (/^\d{4}-\d{2}-\d{2}/.test(node)) {
      for (const part of node.slice(0, 10).split("-")) counts.push(Number(part));
    }
    return;
  }
  if (Array.isArray(node)) {
    for (const item of node) collectNumbers(item, key, prices, percents, counts);
    return;
  }
  if (node && typeof node === "object") {
    for (const [childKey, child] of Object.entries(node)) {
      collectNumbers(child, childKey, prices, percents, counts);
    }
  }
}

export function numbersForDecks(catalog, ids) {
  const prices = [];
  const percents = [];
  const counts = [60, 75, 99, 100];
  const decks = catalog?.decks ?? {};
  for (const id of ids) {
    const deck = decks[id];
    if (!deck) continue;
    collectNumbers(deck, "", prices, percents, counts);
    const main = (deck.mainboard ?? []).reduce((sum, card) => sum + (card.quantity ?? 0), 0);
    const side = (deck.sideboard ?? []).reduce((sum, card) => sum + (card.quantity ?? 0), 0);
    if (main) counts.push(main);
    if (side) counts.push(side);
    if (main && side) counts.push(main + side);
  }
  if (catalog?.fetched_at) collectNumbers(catalog.fetched_at, "fetched_at", prices, percents, counts);
  return { prices, percents, counts };
}

function unmatched(literals, values) {
  return literals.filter((literal) => !values.some((value) => roundsTo(value, literal)));
}

/** Guides written before the claims sidecar: every literal must round to a cited deck fact. */
export function legacyClaimProblems({ file, body, catalog }) {
  const deckIds = Object.keys(catalog?.decks ?? {});
  const allowed = numbersForDecks(catalog, deckIds);
  const found = extractLiterals(body, factNames(null, catalog));
  const problems = [];
  for (const price of unmatched(found.prices, allowed.prices)) {
    problems.push(`${file}: price $${price} does not match the cited deck facts`);
  }
  for (const percent of unmatched(found.percents, allowed.percents)) {
    problems.push(`${file}: percentage ${percent}% does not match the cited deck facts`);
  }
  for (const count of unmatched(found.counts, allowed.counts)) {
    problems.push(`${file}: count ${count} does not match the cited deck facts`);
  }
  return problems;
}

/**
 * Templated guides. Each claim's formatted fact must equal its text, the text
 * must appear in the prose, and every literal in the prose must be a claim.
 */
export function claimProblems({ file, body, claims, facts }) {
  const problems = [];
  if (!Array.isArray(claims) || !claims.length) {
    problems.push(`${file}: missing claims for a templated guide`);
    return problems;
  }
  const texts = [];
  for (const claim of claims) {
    const value = factAt(facts, claim.path);
    const formatted = formatFact(typeof value === "number" ? value : Number.NaN, claim.as);
    if (formatted == null) {
      problems.push(`${file}: claim path ${claim.path} (${claim.as}) is not a ${claim.as} fact`);
      continue;
    }
    if (formatted !== claim.text) {
      problems.push(`${file}: claim ${claim.path} formats as ${formatted}, prose says ${claim.text}`);
    }
    if (!claimAppears(body, claim.text)) {
      problems.push(`${file}: claim ${claim.text} is not in the prose`);
    }
    texts.push(claim.text);
  }
  const found = extractLiterals(body, factNames(facts, null));
  const expected = {
    prices: texts.filter((text) => text.startsWith("$")).map((text) => text.slice(1)),
    percents: texts.filter((text) => text.endsWith("%")).map((text) => text.slice(0, -1)),
    counts: texts.filter((text) => !text.startsWith("$") && !text.endsWith("%")),
  };
  for (const kind of ["prices", "percents", "counts"]) {
    const extras = found[kind].filter((literal) => !expected[kind].includes(literal));
    for (const literal of extras) {
      const label = kind === "prices" ? `$${literal}` : kind === "percents" ? `${literal}%` : literal;
      problems.push(`${file}: ${label} is in the prose and not in the claims`);
    }
  }
  return problems;
}

export function shingleSet(text) {
  const words = String(text)
    .toLowerCase()
    .replace(/<!--[\s\S]*?-->/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter(Boolean);
  const set = new Set();
  for (let index = 0; index <= words.length - SHINGLE; index += 1) {
    set.add(words.slice(index, index + SHINGLE).join(" "));
  }
  return set;
}

export function jaccard(left, right) {
  if (!left.size && !right.size) return 0;
  let intersection = 0;
  for (const item of left) if (right.has(item)) intersection += 1;
  const union = left.size + right.size - intersection;
  return union ? intersection / union : 0;
}

export function similarityProblems(posts, threshold = SIMILARITY_THRESHOLD) {
  const problems = [];
  const sets = posts.map((post) => ({ file: post.file, shingles: shingleSet(post.body) }));
  for (let i = 0; i < sets.length; i += 1) {
    for (let j = i + 1; j < sets.length; j += 1) {
      const score = jaccard(sets[i].shingles, sets[j].shingles);
      if (score > threshold) {
        problems.push(
          `${sets[i].file} and ${sets[j].file}: shingle Jaccard ${score.toFixed(3)} is above ${threshold}`,
        );
      }
    }
  }
  return problems;
}
