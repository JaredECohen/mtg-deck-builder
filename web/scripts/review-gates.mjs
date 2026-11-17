// Extra gates for reviewed: true. No model is called. Card names and legality
// come from the cached Scryfall oracle-cards index. Rule numbers come from the
// dated Comprehensive Rules file. Prices, bans, and "best deck" claims need a
// checked-in data file. A guide needs 1,000 words and a table whose numbers
// are in that data.

import fs from "node:fs";

import { similarityProblems } from "./guide-claims.mjs";
import { wordCount } from "./guide-rubric.mjs";

export const MIN_REVIEWED_WORDS = 1000;

const STOP = new Set(["of", "the", "and", "a", "an", "to", "in", "into", "for", "from", "with", "on", "at", "or", "vs", "versus"]);
const LEAD = new Set(["cast", "casting", "play", "playing", "paying", "calling", "treating", "buying", "open", "opening", "if", "using", "add", "adding", "running", "copy", "copying", "registering", "cut"]);
// Ordinary words that show up capitalized. A one-word token is a card reference only when it is not one of these.
const COMMON_WORD = new Set([
  "about", "after", "again", "against", "already", "also", "another", "around", "because", "before", "being",
  "below", "between", "both", "build", "building", "cannot", "could", "does", "doing", "during", "each", "early",
  "enough", "even", "every", "first", "from", "game", "games", "hand", "hands", "have", "here", "into", "just",
  "keep", "later", "like", "list", "lists", "long", "made", "make", "many", "more", "most", "much", "need",
  "never", "only", "open", "other", "over", "plan", "play", "playing", "read", "same", "should", "some", "still",
  "than", "that", "their", "them", "then", "there", "these", "they", "this", "those", "through", "turn", "turns",
  "under", "until", "using", "very", "want", "what", "when", "where", "which", "while", "with", "without", "would",
  "your", "above", "across", "almost", "always", "among", "anything", "away", "back", "better", "come", "comes",
  "different", "down", "else", "ever", "full", "give", "going", "good", "high", "inside", "instead", "last",
  "leave", "left", "less", "little", "look", "looking", "means", "might", "must", "next", "nothing", "once",
  "order", "part", "point", "rather", "real", "right", "second", "seen", "since", "something", "start", "such",
  "take", "thing", "things", "three", "today", "together", "toward", "true", "used", "usually", "well", "whole",
  "worth", "wrong", "above", "tempo", "aggro", "voltron", "spellslinger",
]);
const GENERIC = new Set([
  "magic", "deck", "decks", "lab", "editorial", "pioneer", "modern", "standard", "legacy", "vintage",
  "commander", "pauper", "brawl", "alchemy", "historic", "timeless", "oathbreaker", "challenger",
  "format", "formats", "guide", "guides", "rules", "comprehensive", "scryfall", "mtgjson", "wizards",
  "coast", "gathering", "content", "policy", "game", "changer", "changers", "today", "bulk", "english",
  "paper", "nonfoil", "official", "product", "products", "list", "lists", "census", "goldfish",
  "sideboard", "main", "total", "price", "prices", "card", "cards", "spell", "spells", "legal",
  "legality", "ban", "bans", "best", "top", "new", "york", "all", "how", "this", "was", "made",
  "short", "answer", "common", "mistakes", "faq", "example", "examples", "when", "choose", "fan",
  "allpricestoday", "tcgplayer", "wizards",
]);

export function normalizeName(name) {
  return String(name)
    .normalize("NFKC")
    .replace(/[’‘]/g, "'")
    .replace(/[,:]/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

export function loadOracle(file) {
  const data = JSON.parse(fs.readFileSync(file, "utf8"));
  const sets = new Set();
  for (const name of data.sets ?? []) {
    const key = normalizeName(name);
    sets.add(key);
    const withoutThe = key.replace(/^the /, "");
    if (withoutThe !== key) sets.add(withoutThe);
  }
  const preferred = new Map();
  const legalityScore = (packed) => [...packed].filter((code) => code === "L" || code === "R" || code === "B").length;
  for (const [name, packed] of Object.entries(data.cards ?? {})) {
    const key = normalizeName(name);
    const row = { name, packed: String(packed) };
    const current = preferred.get(key);
    if (!current || legalityScore(row.packed) > legalityScore(current.packed)) preferred.set(key, row);
  }
  return {
    fetched_at: data.fetched_at ?? "",
    source: data.source ?? "",
    formats: data.formats ?? [],
    byLower: preferred,
    sets,
  };
}

export function loadRules(file) {
  const text = fs.readFileSync(file, "utf8");
  const numbers = new Set();
  for (const line of text.split(/\n/)) {
    const match = line.match(/^(\d{3}(?:\.\d+)?[a-z]?)\b/);
    if (match) numbers.add(match[1]);
  }
  const effective = text.slice(0, 400).match(/effective as of ([A-Za-z]+ \d{1,2}, \d{4})/)?.[1] ?? "";
  return { effective, numbers, source: file };
}

function deckNamesFrom(catalog, facts) {
  const names = [];
  for (const deck of Object.values(catalog?.decks ?? {})) if (deck?.name) names.push(deck.name);
  for (const deck of Object.values(facts?.decks ?? {})) if (deck?.name) names.push(deck.name);
  return names;
}

function prepareProse(body) {
  return String(body)
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^#{1,6} .+$/gm, " ");
}

function tokensOf(span) {
  return span
    .replace(/[’‘]/g, "'")
    .replace(/\s*\/\/\s*/g, " // ")
    .replace(/[,:;]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean);
}

function lookupKeys(phrase) {
  const primary = normalizeName(phrase);
  const stripped = normalizeName(phrase.replace(/'s$/i, ""));
  return stripped === primary ? [primary] : [primary, stripped];
}

function contentWords(words) {
  return words.filter((word) => word !== "//" && !STOP.has(word.toLowerCase()));
}

function isGeneric(words) {
  const content = contentWords(words);
  return content.length > 0 && content.every((word) => GENERIC.has(word.toLowerCase().replace(/[^a-z-]/gi, "")));
}

const SMALL = "of|the|and|a|an|to|in|into|for|from|with|on|at|or|vs\\.?";
const NAME = "[A-Z][\\p{L}\\p{N}'’\\-]*";
const SPAN = new RegExp(`\\b(${NAME}(?:\\s*(?:\\/\\/|,)?\\s+(?:${NAME}|${SMALL})){1,12})\\b`, "gu");

function expandDeckNames(deckNames) {
  const names = new Set();
  for (const raw of deckNames.filter(Boolean)) {
    names.add(raw);
    for (const match of String(raw).matchAll(/\(([^)]+)\)/g)) names.add(match[1]);
    const noParen = String(raw).replace(/\s*\([^)]*\)\s*/g, " ").replace(/\s+/g, " ").trim();
    if (noParen) names.add(noParen);
    const stripped = noParen.replace(/^\d+\s+/, "");
    if (stripped) names.add(stripped);
  }
  return names;
}

function productNickname(phrase, decks) {
  const words = String(phrase).split(" ").filter(Boolean);
  if (words.length !== 2) return false;
  if (!["challenger", "deck", "precon", "product"].includes(words[1].toLowerCase())) return false;
  const head = normalizeName(words[0]);
  if (head.length < 4) return false;
  for (const name of decks) {
    if (name === head || name.startsWith(`${head} `) || name.includes(` ${head} `) || name.endsWith(` ${head}`)) return true;
  }
  return false;
}

function findKnown(phrase, oracle, decks) {
  for (const key of lookupKeys(phrase)) {
    if (decks.has(key)) return { kind: "deck" };
    const card = oracle?.byLower?.get(key);
    if (card) return { kind: "card", card };
    if (oracle?.sets?.has(key)) return { kind: "set" };
  }
  return null;
}

function coverRun(words, oracle, decks) {
  const covered = new Array(words.length).fill(false);
  for (let size = words.length; size >= 1; size -= 1) {
    for (let start = 0; start + size <= words.length; start += 1) {
      if (covered.slice(start, start + size).every(Boolean)) continue;
      const slice = words.slice(start, start + size);
      if (!contentWords(slice).length) continue;
      if (size === 1) {
        const word = slice[0].replace(/'s$/i, "");
        if (findKnown(word, oracle, decks)) covered[start] = true;
        continue;
      }
      if (findKnown(slice.join(" "), oracle, decks) || isGeneric(slice) || productNickname(slice.join(" "), decks)) {
        for (let index = start; index < start + size; index += 1) covered[index] = true;
      }
    }
  }
  const problems = [];
  let run = [];
  const flush = () => {
    let trimmed = [...run];
    while (trimmed.length && STOP.has(trimmed[0].toLowerCase())) trimmed.shift();
    while (trimmed.length && STOP.has(trimmed[trimmed.length - 1].toLowerCase())) trimmed.pop();
    const content = contentWords(trimmed);
    if (content.length && LEAD.has(content[0].replace(/'s$/i, "").toLowerCase())) {
      const at = trimmed.findIndex((word) => word.replace(/'s$/i, "").toLowerCase() === content[0].replace(/'s$/i, "").toLowerCase());
      trimmed = trimmed.slice(at + 1);
    }
    const groups = [[]];
    for (const word of trimmed) {
      if (word.toLowerCase() === "and" || word.toLowerCase() === "or") groups.push([]);
      else groups[groups.length - 1].push(word);
    }
    for (const group of groups) {
      const words = [...group];
      while (words.length && STOP.has(words[0].toLowerCase())) words.shift();
      while (words.length && STOP.has(words[words.length - 1].toLowerCase())) words.pop();
      const left = contentWords(words);
      if (left.length >= 2 && !productNickname(words.join(" "), decks)) problems.push(words.join(" "));
    }
    run = [];
  };
  for (let index = 0; index < words.length; index += 1) {
    if (covered[index]) flush();
    else run.push(words[index]);
  }
  flush();
  return problems;
}

/** Title-case spans that are not a Scryfall card, a set, a known deck, or a generic phrase. */
export function unresolvedCardNames(body, oracle, deckNames = []) {
  const decks = new Set([...expandDeckNames(deckNames)].map(normalizeName));
  const problems = [];
  const seen = new Set();
  const push = (label) => {
    if (!label || seen.has(label)) return;
    seen.add(label);
    problems.push(label);
  };
  const prose = prepareProse(body);
  for (const match of prose.matchAll(SPAN)) {
    for (const label of coverRun(tokensOf(match[1]), oracle, decks)) push(label);
  }
  const single = /\b([A-Z][\p{L}'’]{4,})\b/gu;
  const nameWords = new Set();
  for (const name of [...decks, ...oracle.byLower.keys(), ...(oracle.sets ?? [])]) {
    for (const part of name.split(/[\s-]+/)) if (part.length >= 4) nameWords.add(part);
  }
  for (const match of prose.matchAll(single)) {
    const word = match[1];
    const lower = normalizeName(word);
    if (lower.endsWith("ing")) continue;
    if (GENERIC.has(lower) || STOP.has(lower) || LEAD.has(lower) || COMMON_WORD.has(lower)) continue;
    if (findKnown(word, oracle, decks) || nameWords.has(lower)) continue;
    const before = prose.slice(Math.max(0, match.index - 16), match.index);
    const after = prose.slice(match.index + word.length, match.index + word.length + 48);
    // Part of a longer title-case name, not a standalone card.
    if (/[A-Z][\p{L}'’]*\s+$/u.test(before) || /^\s+[A-Z]/u.test(after)) continue;
    const sentence = `${before} ${word} ${after}`.toLowerCase();
    const cued = /\d+\s+$/.test(before)
      || /\b(?:cast|casts|play|plays|played)\s+$/.test(before.toLowerCase())
      || /\b(?:banned|legal)\b/.test(sentence);
    if (!cued) continue;
    push(word);
  }
  const quantity = new RegExp(`\\b\\d+\\s+([A-Z][\\p{L}\\p{N}'’\\-]*(?:\\s*(?:,|\\/\\/)?\\s+(?:[A-Z][\\p{L}\\p{N}'’\\-]*|${SMALL})){0,8})`, "gu");
  for (const match of prose.matchAll(quantity)) {
    if (match.index > 0 && /[-/\d]/.test(prose[match.index - 1])) continue;
    const words = tokensOf(match[1]);
    if (words.length >= 2) continue;
    const word = words[0] ?? "";
    if (GENERIC.has(word.toLowerCase()) || STOP.has(word.toLowerCase())) continue;
    const known = findKnown(word, oracle, decks);
    if (!known) push(word);
  }
  return problems;
}

function cardsIn(text, oracle, deckNames) {
  const decks = new Set([...expandDeckNames(deckNames)].map(normalizeName));
  const found = [];
  const seen = new Set();
  const prose = prepareProse(text);
  for (const match of prose.matchAll(SPAN)) {
    const words = tokensOf(match[1]);
    for (let size = words.length; size >= 2; size -= 1) {
      for (let start = 0; start + size <= words.length; start += 1) {
        const hit = findKnown(words.slice(start, start + size).join(" "), oracle, decks);
        if (hit?.kind === "card" && !seen.has(hit.card.name)) {
          seen.add(hit.card.name);
          found.push(hit.card);
        }
      }
    }
  }
  for (const match of prose.matchAll(/\b([A-Z][\p{L}'’]{4,})\b/gu)) {
    const before = prose.slice(Math.max(0, match.index - 16), match.index);
    const after = prose.slice(match.index + match[1].length, match.index + match[1].length + 16);
    if (/[A-Z][\p{L}'’]*\s+$/u.test(before) || /^\s+[A-Z]/u.test(after)) continue;
    const hit = findKnown(match[1], oracle, decks);
    if (hit?.kind === "card" && !seen.has(hit.card.name)) {
      seen.add(hit.card.name);
      found.push(hit.card);
    }
  }
  return found;
}

function legalityStatus(sentence) {
  const text = sentence.toLowerCase();
  if (/\b(?:is|was|were|been|are)\s+banned\b/.test(text) || /\bbanned in\b/.test(text)) return "banned";
  if (/\b(?:is|was|were|been|are)\s+restricted\b/.test(text) || /\brestricted in\b/.test(text)) return "restricted";
  if (/\bnot\s+(?:\w+-)?legal\b/.test(text) || /\bisn'?t\s+legal\b/.test(text) || /\bnot\s+\w+-legal\b/.test(text)) return "not_legal";
  if (/\b(?:is|are|was|were)\s+legal\b/.test(text) || /(?<!not\s)(?<!n't\s)\b[a-z]+-legal\b/.test(text)) return "legal";
  return null;
}

const FORMAT_PATTERN = /\b(?:in|for)\s+(standard|pioneer|modern|legacy|vintage|commander|pauper)\b|(standard|pioneer|modern|legacy|vintage|commander|pauper)-legal\b|\b(standard|pioneer|modern|legacy|vintage|pauper)\b/gi;

function formatIn(text) {
  FORMAT_PATTERN.lastIndex = 0;
  const match = FORMAT_PATTERN.exec(text);
  if (!match) return null;
  return (match[1] || match[2] || match[3]).toLowerCase();
}

function lastFormat(text) {
  let found = null;
  for (const match of String(text).matchAll(FORMAT_PATTERN)) found = (match[1] || match[2] || match[3]).toLowerCase();
  return found;
}

function codeMatches(status, code) {
  if (!code || code === "?") return false;
  if (status === "banned") return code === "B";
  if (status === "restricted") return code === "R";
  if (status === "legal") return code === "L" || code === "R";
  if (status === "not_legal") return code === "N" || code === "B";
  return false;
}

export function legalityProblems({ file, body, oracle, deckNames, catalog }) {
  if (!oracle?.byLower?.size) return [`${file}: legality claims have no Scryfall index`];
  const problems = [];
  const source = String(body);
  const paragraphs = source.split(/\n\s*\n/);
  for (const paragraph of paragraphs) {
    const sentences = paragraph.split(/\n+|(?<=[.!?])\s+/);
    for (const sentence of sentences) {
      const status = legalityStatus(sentence);
      if (!status) continue;
      const at = source.indexOf(sentence);
      const format = formatIn(sentence) ?? lastFormat(source.slice(Math.max(0, at - 4000), at));
      const formatIndex = oracle.formats.indexOf(format);
      const named = cardsIn(sentence, oracle, deckNames);
      if (!format || formatIndex < 0) {
        if (named.length) problems.push(`${file}: ${named[0].name} legality claim has no format`);
        continue;
      }
      for (const card of named) {
        const code = card.packed[formatIndex] ?? "?";
        if (!codeMatches(status, code)) {
          problems.push(`${file}: ${card.name} is ${status.replace("_", " ")} in ${format} but Scryfall says "${code}"`);
        }
      }
    }
  }
  const every = /\bevery card in ([^.\n]+?) is legal in (standard|pioneer|modern|legacy|vintage|commander|pauper)\b/gi;
  for (const match of String(body).matchAll(every)) {
    const deckName = match[1].trim();
    const format = match[2].toLowerCase();
    const formatIndex = oracle.formats.indexOf(format);
    const deck = Object.values(catalog?.decks ?? {}).find((item) => normalizeName(item.name) === normalizeName(deckName));
    if (!deck) {
      problems.push(`${file}: "every card in ${deckName}" does not name a deck in the catalog`);
      continue;
    }
    const names = [
      ...(deck.mainboard ?? []).map((card) => card.name),
      ...(deck.sideboard ?? []).map((card) => card.name),
      ...(deck.commanders ?? []),
      ...(deck.commander ? [deck.commander] : []),
    ];
    for (const name of names) {
      const card = oracle.byLower.get(normalizeName(name));
      const code = card?.packed?.[formatIndex] ?? "?";
      if (!codeMatches("legal", code)) {
        problems.push(`${file}: ${name} is not legal in ${format} on the Scryfall index (${code})`);
      }
    }
  }
  return problems;
}

function ruleCitations(body) {
  const cites = new Set();
  const text = String(body)
    .replace(/https?:\/\/\S+/g, " ")
    .replace(/\$\d+(?:\.\d+)?/g, " ")
    .replace(/\d+(?:\.\d+)?%/g, " ");
  for (const match of text.matchAll(/\brules?\s+(\d{3}(?:\.\d+)?[a-z]?)\b/gi)) cites.add(match[1]);
  for (const match of text.matchAll(/\b(\d{3}\.\d+[a-z]?)\b/g)) {
    if (/^\d{3}\.\d{2}$/.test(match[1])) continue;
    cites.add(match[1]);
  }
  return [...cites];
}

export function rulesProblems({ file, body, rules }) {
  if (!rules?.numbers?.size) return [`${file}: Comprehensive Rules file is missing`];
  const problems = [];
  for (const cite of ruleCitations(body)) {
    if (!rules.numbers.has(cite)) problems.push(`${file}: Comprehensive Rules citation ${cite} is not in the ${rules.effective || "dated"} rules file`);
  }
  return problems;
}

function sourcedNumbers({ claims, catalog, body }) {
  const prices = new Set();
  const ints = new Set();
  const addPrice = (value) => {
    const number = Number(value);
    if (Number.isFinite(number)) prices.add(number.toFixed(2));
  };
  const addInt = (value) => {
    const number = Number(value);
    if (Number.isInteger(number)) ints.add(String(number));
  };
  for (const claim of claims ?? []) {
    const text = String(claim?.text ?? "");
    if (text.startsWith("$")) addPrice(text.slice(1));
    else if (/^\d+$/.test(text)) addInt(text);
  }
  const ids = [...String(body).matchAll(/<DeckBlock\s+id="([^"]+)"/g)].map((match) => match[1]);
  for (const id of ids) {
    const deck = catalog?.decks?.[id];
    if (!deck) continue;
    const analysis = deck.analysis ?? {};
    for (const key of ["total_cost_usd", "basic_land_cost_usd", "top3_cost_usd"]) addPrice(analysis[key]);
    for (const key of ["priced_cards", "land_count", "nonland_count"]) addInt(analysis[key]);
    for (const point of analysis.mana_curve ?? []) addInt(point?.count ?? point?.card_count);
    for (const card of analysis.top_cards ?? []) {
      addPrice(card?.usd);
      addPrice(card?.line_usd);
    }
    for (const card of [...(deck.mainboard ?? []), ...(deck.sideboard ?? [])]) addInt(card?.quantity);
    const goldfish = analysis.goldfish ?? {};
    addInt(goldfish.games);
    addInt(goldfish.seed);
  }
  return { prices, ints };
}

function tablesOf(body) {
  const tables = [];
  let current = [];
  for (const line of String(body).split("\n")) {
    if (/^\s*\|/.test(line)) current.push(line);
    else if (current.length) {
      tables.push(current.join("\n"));
      current = [];
    }
  }
  if (current.length) tables.push(current.join("\n"));
  return tables;
}

function meaningfulTableHits(table, sourced) {
  const hits = new Set();
  for (const match of table.matchAll(/\$(\d+(?:\.\d+)?)/g)) {
    const formatted = Number(match[1]).toFixed(2);
    if (sourced.prices.has(formatted)) hits.add(`$${formatted}`);
  }
  for (const match of table.matchAll(/\b(\d+)\b/g)) {
    const value = Number(match[1]);
    // Copy counts of 1–4 show up in almost any list and do not make a table sourced.
    if (value >= 1 && value <= 4) continue;
    if (sourced.ints.has(match[1])) hits.add(match[1]);
  }
  return hits;
}

export function dataTableProblems({ file, body, claims, catalog }) {
  const tables = tablesOf(body);
  const sourced = sourcedNumbers({ claims, catalog, body });
  const declared = Array.isArray(claims) && claims.length > 0;
  const backed = tables.some((table) => {
    const hits = meaningfulTableHits(table, sourced);
    if (hits.size >= 2) return true;
    return declared && hits.size >= 1;
  });
  if (!backed) return [`${file}: no table built from a sourced data file`];
  return [];
}

export function sourcedClaimProblems({ file, body, claims }) {
  const problems = [];
  const hasClaims = Array.isArray(claims) && claims.length > 0;
  const hasDeck = /<DeckBlock\s+id="[^"]+"/.test(body);
  if (/\$\d/.test(body) && !hasClaims && !hasDeck) problems.push(`${file}: price claim without a sourced data file`);
  if (/\b(?:is|was|were|been|are)\s+banned\b|\bbanned in\b/i.test(body) && !hasClaims && !hasDeck) {
    problems.push(`${file}: ban claim without a sourced data file`);
  }
  const bestDeck = /\bbest decks?\b/i.test(body);
  const bestCards = /(?<!opponent's )(?<!your )\bbest cards\b/i.test(body);
  if ((bestDeck || bestCards) && !hasClaims) problems.push(`${file}: best-deck claim without a sourced data file`);
  return problems;
}

export function reviewGateProblems({ file, body, oracle, rules, catalog, deckNames, claims }) {
  const problems = [];
  const words = wordCount(body);
  if (words < MIN_REVIEWED_WORDS) problems.push(`${file}: ${words} words (reviewed guides need at least ${MIN_REVIEWED_WORDS})`);
  for (const name of unresolvedCardNames(body, oracle, deckNames)) {
    problems.push(`${file}: card name not in the Scryfall index: ${name}`);
  }
  problems.push(...legalityProblems({ file, body, oracle, deckNames, catalog }));
  problems.push(...rulesProblems({ file, body, rules }));
  problems.push(...sourcedClaimProblems({ file, body, claims }));
  problems.push(...dataTableProblems({ file, body, claims, catalog }));
  return problems;
}

/** Pairwise outline failures. Shared headings are included. */
export function outlineGateProblems(posts) {
  return similarityProblems(posts).filter((line) => line.includes("section outline"));
}

