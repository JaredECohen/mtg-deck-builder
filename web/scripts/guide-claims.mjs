// Numeric claims and near-duplicate checks for reviewed guides.
// Prices, percentages, and counts in a claims sidecar must equal the facts
// file. Guides without a sidecar are checked against the example-deck catalog
// they cite. No model is called.

export const SIMILARITY_THRESHOLD = 0.15;

const NUMBER_WORDS = {
  zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10,
  eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17, eighteen: 18, nineteen: 19,
  twenty: 20, thirty: 30, forty: 40, fifty: 50, sixty: 60, seventy: 70, eighty: 80, ninety: 90, hundred: 100,
};
const ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];
const TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"];

export function spellNumber(value) {
  const number = Math.round(Number(value));
  if (!Number.isInteger(number) || number < 0 || number > 100 || Math.abs(number - Number(value)) > 1e-6) return null;
  if (number < 10) return ONES[number];
  if (number < 20) return Object.entries(NUMBER_WORDS).find(([, amount]) => amount === number)?.[0] ?? null;
  if (number === 100) return "hundred";
  const ten = Math.floor(number / 10);
  const one = number % 10;
  return one === 0 ? TENS[ten] : `${TENS[ten]}-${ONES[one]}`;
}

export function numberWordValue(word) {
  const text = String(word).toLowerCase();
  if (Object.prototype.hasOwnProperty.call(NUMBER_WORDS, text)) return NUMBER_WORDS[text];
  const compound = text.match(/^(twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)-(one|two|three|four|five|six|seven|eight|nine)$/);
  if (!compound) return null;
  return NUMBER_WORDS[compound[1]] + NUMBER_WORDS[compound[2]];
}
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
  if (kind === "words") return spellNumber(value);
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
    .replace(/\[[^\]]*\]\([^)]*\)/g, " ")
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
  const spelled = stripped.match(
    /\b(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)-(?:one|two|three|four|five|six|seven|eight|nine)\b|(?<!-)\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\b(?!-)/gi,
  );
  if (spelled) counts.push(...spelled.map((word) => word.toLowerCase()));
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
  const counts = [];
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

function citedDecks(catalog, ids) {
  const decks = catalog?.decks ?? {};
  return ids.map((id) => decks[id]).filter(Boolean);
}

/**
 * A deck total may appear anywhere. A card price may appear only beside that
 * card's name, so swapping the list total for a card's price fails.
 */
function priceWindowOk(before, literal, decks) {
  const window = before.slice(-220);
  for (const deck of decks) {
    const analysis = deck.analysis ?? {};
    for (const key of ["total_cost_usd", "basic_land_cost_usd", "top3_cost_usd"]) {
      if (typeof analysis[key] === "number" && roundsTo(analysis[key], literal)) return true;
    }
    for (const card of analysis.top_cards ?? []) {
      const priced = [card.usd, card.line_usd].some((value) => typeof value === "number" && roundsTo(value, literal));
      if (!priced) continue;
      const short = String(card.name ?? "").split(",")[0];
      if ((card.name && window.includes(card.name)) || (short.length > 3 && window.includes(short))) return true;
    }
  }
  return false;
}

export function misplacedPrices(body, catalog, ids) {
  const decks = citedDecks(catalog, ids);
  const problems = [];
  const pattern = /\$(\d+(?:\.\d+)?)/g;
  for (const match of String(body).matchAll(pattern)) {
    if (priceWindowOk(body.slice(0, match.index), match[1], decks)) continue;
    problems.push(match[1]);
  }
  return problems;
}

/** Guides written before the claims sidecar: every literal must round to a cited deck fact. */
function countLiteral(literal) {
  if (/^\d/.test(literal)) return literal;
  const value = numberWordValue(literal);
  return value == null ? null : String(value);
}

function deckIdsIn(body) {
  return [...String(body).matchAll(/<DeckBlock\s+id="([^"]+)"/g)].map((match) => match[1]);
}

function pricePercentCountProblems({ file, text, allowed, catalog, deckIds, where }) {
  const problems = [];
  const found = extractLiterals(text, factNames(null, catalog));
  for (const price of misplacedPrices(text, catalog, deckIds)) {
    problems.push(`${file}: price $${price} in the ${where} does not match the cited deck facts`);
  }
  for (const percent of unmatched(found.percents, allowed.percents)) {
    problems.push(`${file}: percentage ${percent}% in the ${where} does not match the cited deck facts`);
  }
  for (const count of unmatched(found.counts.map(countLiteral).filter(Boolean), allowed.counts)) {
    problems.push(`${file}: count ${count} in the ${where} does not match the cited deck facts`);
  }
  return problems;
}

export function legacyClaimProblems({ file, body, catalog }) {
  const deckIds = deckIdsIn(body);
  const allowed = numbersForDecks(catalog, deckIds);
  return pricePercentCountProblems({ file, text: body, allowed, catalog, deckIds, where: "prose" });
}

/** Title and description use the decks the article cites, not a separate source. */
export function legacyHeadlineProblems({ file, title, description, body, catalog }) {
  const headline = `${title ?? ""}\n${description ?? ""}`.trim();
  if (!headline) return [];
  const deckIds = deckIdsIn(body);
  const allowed = numbersForDecks(catalog, deckIds);
  return pricePercentCountProblems({ file, text: headline, allowed, catalog, deckIds, where: "title or description" });
}

function claimTexts(claims) {
  return (claims ?? []).map((claim) => claim.text);
}

export function headlineLiteralProblems({ file, title, description, claims, facts }) {
  const headline = `${title ?? ""}\n${description ?? ""}`.trim();
  if (!headline) return [];
  const texts = claimTexts(claims);
  const found = extractLiterals(headline, factNames(facts, null));
  const expected = {
    prices: texts.filter((text) => text.startsWith("$")).map((text) => text.slice(1)),
    percents: texts.filter((text) => text.endsWith("%")).map((text) => text.slice(0, -1)),
    counts: texts.filter((text) => !text.startsWith("$") && !text.endsWith("%")),
  };
  const problems = [];
  for (const kind of ["prices", "percents", "counts"]) {
    const extras = found[kind].filter((literal) => !expected[kind].includes(literal));
    for (const literal of extras) {
      const label = kind === "prices" ? `$${literal}` : kind === "percents" ? `${literal}%` : literal;
      problems.push(`${file}: ${label} is in the title or description and not in the claims`);
    }
  }
  return problems;
}

function hitsIn(text, names) {
  const found = [];
  const taken = [];
  const ordered = names.filter((name) => typeof name === "string" && name.length > 2 && text.includes(name));
  ordered.sort((left, right) => right.length - left.length);
  for (const name of ordered) {
    let from = 0;
    while (from < text.length) {
      const index = text.indexOf(name, from);
      if (index < 0) break;
      const end = index + name.length;
      const beforeOk = index === 0 || !/[A-Za-z0-9]/.test(text[index - 1]);
      const afterOk = end >= text.length || !/[A-Za-z0-9]/.test(text[end]);
      const overlaps = taken.some(([start, stop]) => index < stop && end > start);
      if (beforeOk && afterOk && !overlaps) {
        taken.push([index, end]);
        found.push(name);
        break;
      }
      from = index + 1;
    }
  }
  return found;
}

function maskDeckNames(text, deckNames) {
  let masked = text;
  for (const name of [...deckNames].sort((left, right) => right.length - left.length)) {
    masked = masked.split(name).join(" ".repeat(name.length));
  }
  return masked;
}

/**
 * A sentence that puts a card in a deck must name a deck that actually contains it.
 * "Farewell is in Arcane Maelstrom" fails. "Farewell is in Timey-Wimey" does not.
 */
export function cardDeckProblems({ file, text, decks }) {
  if (!decks?.length) return [];
  const deckNames = decks.map((deck) => deck.name);
  const cardsByDeck = new Map(decks.map((deck) => [deck.name, new Set(deck.cards ?? [])]));
  const allCards = [...new Set(decks.flatMap((deck) => deck.cards ?? []))];
  const problems = [];
  for (const sentence of String(text).split(/\n+|(?<=[.!?])\s+/)) {
    const verbs = [
      { pattern: /\bis in\b/i, cardsFirst: true },
      { pattern: /\bshows up in\b/i, cardsFirst: true },
      { pattern: /\bincludes\b/i, cardsFirst: false },
      { pattern: /\bGame Changer is\b/i, cardsFirst: false },
    ];
    for (const verb of verbs) {
      const match = verb.pattern.exec(sentence);
      if (!match) continue;
      const before = sentence.slice(0, match.index);
      const after = sentence.slice(match.index + match[0].length);
      const beforeDecks = hitsIn(before, deckNames);
      const afterDecks = hitsIn(after, deckNames);
      const beforeCards = hitsIn(maskDeckNames(before, deckNames), allCards);
      const afterCards = hitsIn(maskDeckNames(after, deckNames), allCards);
      const cards = verb.cardsFirst ? beforeCards : afterCards;
      const namedDecks = verb.cardsFirst ? afterDecks : beforeDecks;
      for (const card of cards) {
        for (const deck of namedDecks) {
          if (!cardsByDeck.get(deck)?.has(card)) {
            problems.push(`${file}: ${card} is not in ${deck}`);
          }
        }
      }
    }
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
    if (!claim.context || !body.includes(claim.context)) {
      problems.push(`${file}: claim ${claim.text} is not tied to its sentence`);
    } else if (!claim.context.includes(claim.text)) {
      problems.push(`${file}: claim context for ${claim.text} does not contain that value`);
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

export function maskComparable(text, names = []) {
  let masked = String(text);
  const ordered = [...names].filter((name) => typeof name === "string" && name.length > 3).sort((a, b) => b.length - a.length);
  for (const name of ordered) masked = masked.split(name).join(" card ");
  return masked.replace(/\$?\d+(?:\.\d+)?%?/g, " n ").replace(
    /\b(?:twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)-(?:one|two|three|four|five|six|seven|eight|nine)\b|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\b/gi,
    " n ",
  );
}

export function similarityProblems(posts, threshold = SIMILARITY_THRESHOLD, names = []) {
  const problems = [];
  const sets = posts.map((post) => ({
    file: post.file,
    shingles: shingleSet(post.body),
    masked: shingleSet(maskComparable(post.body, names)),
  }));
  for (let i = 0; i < sets.length; i += 1) {
    for (let j = i + 1; j < sets.length; j += 1) {
      const score = jaccard(sets[i].shingles, sets[j].shingles);
      const masked = jaccard(sets[i].masked, sets[j].masked);
      if (score > threshold || masked > threshold) {
        problems.push(
          `${sets[i].file} and ${sets[j].file}: shingle Jaccard ${Math.max(score, masked).toFixed(3)} is above ${threshold}`,
        );
      }
    }
  }
  return problems;
}
