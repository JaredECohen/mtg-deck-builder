// Role counts for the reviewed archetype guides.
// Card text is the pinned Scryfall oracle subset in example-card-oracle.json.
// Ramp names are the precon_facts lists, which already applied the ramp rules.
// No model is called.

import fs from "node:fs";

function stripReminder(text) {
  const kept = [];
  let depth = 0;
  for (const char of text || "") {
    if (char === "(") {
      depth += 1;
      continue;
    }
    if (char === ")" && depth) {
      depth -= 1;
      continue;
    }
    if (depth === 0) kept.push(char);
  }
  return kept.join("");
}

function frontTypes(typeLine) {
  return String(typeLine || "").split("//")[0].split("—")[0].split("–")[0];
}

function isLand(typeLine) {
  return frontTypes(typeLine).split(/\s+/).includes("Land");
}

function primary(typeLine) {
  const face = frontTypes(typeLine);
  for (const label of ["Creature", "Planeswalker", "Instant", "Sorcery", "Artifact", "Enchantment", "Battle"]) {
    if (face.split(/\s+/).includes(label)) return label;
  }
  return "Other";
}

function rowsOf(deck, { side = false, commander = false } = {}) {
  const rows = [...(deck.mainboard ?? [])];
  if (side) rows.push(...(deck.sideboard ?? []));
  if (commander && deck.commander) rows.push({ name: deck.commander, quantity: 1 });
  return rows;
}

function infoOf(oracle, name) {
  const info = oracle[name];
  if (!info) throw new Error(`missing oracle text for ${name}`);
  return info;
}

function youCreateCreatureToken(text) {
  const parts = stripReminder(text).split(/[.\n]/);
  return parts.some((sentence) => {
    if (!/\bcreate/i.test(sentence)) return false;
    if (!/\b\d+\/\d+\b/i.test(sentence) && !/creature token/i.test(sentence)) return false;
    if (/controller creates/i.test(sentence)) return false;
    if (/\b(an opponent|each opponent|target opponent)\b/i.test(sentence) && /\bcreates?\b/i.test(sentence)) return false;
    return true;
  });
}

function isAnthem(text) {
  return /(creatures you control|creature tokens you control|other creatures you control|creatures you control of the chosen type) get \+/i.test(stripReminder(text));
}

function isSpell(typeLine) {
  const kind = primary(typeLine);
  return kind === "Instant" || kind === "Sorcery";
}

function hasX(text) {
  return /\bX\b/.test(stripReminder(text));
}

function grantsProtection(text, keywords) {
  const body = stripReminder(text).toLowerCase();
  const keys = (keywords ?? []).map((word) => word.toLowerCase());
  const blob = `${body} ${keys.join(" ")}`;
  return ["hexproof", "shroud", "indestructible", "protection from"].some((needle) => blob.includes(needle));
}

function countersOrExilesSpell(text) {
  const body = stripReminder(text);
  return /\bcounter target\b/i.test(body) || /\bexile target spell\b/i.test(body);
}

function isSacrificeOutlet(text) {
  const body = stripReminder(text);
  return /sacrifice (?:a|another) (?:creature|vampire|artifact|permanent)/i.test(body);
}

function isDeathPayoff(text, typeLine) {
  if (String(typeLine).includes("Equipment")) return false;
  return /whenever .{0,80}dies/i.test(stripReminder(text));
}

function isCreatureAura(text, typeLine) {
  if (!String(typeLine).includes("Aura")) return false;
  const body = stripReminder(text);
  if (/enchant (?:forest|land)\b/i.test(body)) return false;
  return /enchant (?:creature|artifact or creature)/i.test(body);
}

const MILL_WORDS = {
  one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10,
  eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15,
};

function millNumber(oracle, name) {
  const text = stripReminder(infoOf(oracle, name).oracle_text);
  const match = text.match(/\bmills?\s+(one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|\d+)\b/i);
  if (!match) throw new Error(`${name} has no fixed mill number`);
  const raw = match[1].toLowerCase();
  return MILL_WORDS[raw] ?? Number(raw);
}

function manaValue(oracle, name) {
  return Number(infoOf(oracle, name).cmc);
}

function isReanimationSpell(text, typeLine) {
  if (isLand(typeLine)) return false;
  if (primary(typeLine) === "Creature") return false;
  const body = stripReminder(text).replace(/\s+/g, " ");
  if (/enchant creature card in a graveyard/i.test(body) && /return enchanted creature card to the battlefield/i.test(body)) return true;
  return /(?:return|put) .{0,120}creature card.{0,100}(?:graveyard|battlefield)/i.test(body);
}

function countWhere(deck, oracle, predicate, options) {
  let copies = 0;
  const names = [];
  for (const card of rowsOf(deck, options)) {
    const info = infoOf(oracle, card.name);
    if (!predicate(info, card)) continue;
    copies += card.quantity;
    names.push(`${card.quantity} ${card.name}`);
  }
  return { copies, names };
}

function rampByFile(preconFacts) {
  const map = new Map();
  for (const deck of Object.values(preconFacts?.decks ?? {})) map.set(deck.file_name, deck);
  return map;
}

function rampRole(deck, oracle, preconFacts) {
  const facts = rampByFile(preconFacts).get(deck.mtgjson_file);
  if (!facts) throw new Error(`no precon facts for ${deck.mtgjson_file}`);
  const buckets = {};
  let max = 0;
  for (const card of facts.ramp_cards ?? []) {
    const info = infoOf(oracle, card.name);
    const mv = Number(info.cmc);
    buckets[mv] = (buckets[mv] ?? 0) + card.quantity;
    if (mv > max) max = mv;
  }
  const creatures = countWhere(deck, oracle, (info) => !isLand(info.type_line) && primary(info.type_line) === "Creature" && Number(info.cmc) >= 6);
  const atNine = countWhere(deck, oracle, (info) => !isLand(info.type_line) && primary(info.type_line) === "Creature" && Number(info.cmc) >= 9);
  return {
    ramp_count: facts.ramp_count,
    ramp_mv_1: buckets[1] ?? 0,
    ramp_mv_2: buckets[2] ?? 0,
    ramp_mv_3: buckets[3] ?? 0,
    ramp_mv_4: buckets[4] ?? 0,
    ramp_mv_3_or_4: (buckets[3] ?? 0) + (buckets[4] ?? 0),
    ramp_mv_max: max,
    creatures_mv_6_plus: creatures.copies,
    creatures_mv_9_plus: atNine.copies,
    _names: { ramp: (facts.ramp_cards ?? []).map((card) => card.name), big: creatures.names, nine: atNine.names },
  };
}

function spellRole(deck, oracle) {
  const instants = countWhere(deck, oracle, (info) => !isLand(info.type_line) && primary(info.type_line) === "Instant");
  const sorceries = countWhere(deck, oracle, (info) => !isLand(info.type_line) && primary(info.type_line) === "Sorcery");
  const fixedCheap = countWhere(deck, oracle, (info) => isSpell(info.type_line) && Number(info.cmc) <= 2 && !hasX(info.oracle_text));
  const xCheap = countWhere(deck, oracle, (info) => isSpell(info.type_line) && Number(info.cmc) <= 2 && hasX(info.oracle_text));
  const counters = countWhere(deck, oracle, (info) => /\bcounter target\b/i.test(stripReminder(info.oracle_text)));
  const creatures = countWhere(deck, oracle, (info) => primary(info.type_line) === "Creature");
  return {
    instant_count: instants.copies,
    sorcery_count: sorceries.copies,
    instant_or_sorcery: instants.copies + sorceries.copies,
    fixed_cheap_spells: fixedCheap.copies,
    x_spells_mv_2_or_less: xCheap.copies,
    counter_target_count: counters.copies,
    creature_count: creatures.copies,
    _names: { fixedCheap: fixedCheap.names, xCheap: xCheap.names, counters: counters.names, creatures: creatures.names },
  };
}

const BUILDERS = {
  "mind-flayarrrs"(deck, oracle) {
    const mainboard = rowsOf(deck).reduce((sum, card) => sum + card.quantity, 0);
    const library = mainboard - 7;
    const life = deck.analysis.goldfish.starting_life;
    return {
      library_after_opening_hand: library,
      fractured_sanity_mill: millNumber(oracle, "Fractured Sanity"),
      nemesis_attack_mill: millNumber(oracle, "Nemesis of Reason"),
      library_left_if_40_life_is_milled: library - life,
    };
  },
  "sneak-attack"(deck, oracle) {
    const mainboard = rowsOf(deck).reduce((sum, card) => sum + card.quantity, 0);
    return {
      library_after_opening_hand: mainboard - 7,
      rogue_attack_mill: millNumber(oracle, "Soaring Thought-Thief"),
    };
  },
  "token-triumph"(deck, oracle) {
    const makers = countWhere(deck, oracle, (info) => !isLand(info.type_line) && youCreateCreatureToken(info.oracle_text));
    const anthems = countWhere(deck, oracle, (info) => !isLand(info.type_line) && isAnthem(info.oracle_text));
    const landMakers = countWhere(deck, oracle, (info) => isLand(info.type_line) && youCreateCreatureToken(info.oracle_text));
    return {
      token_makers: makers.copies,
      anthems: anthems.copies,
      land_token_makers: landMakers.copies,
      _names: { makers: makers.names, anthems: anthems.names, lands: landMakers.names },
    };
  },
  "rebellion-rising"(deck, oracle) {
    const makers = countWhere(deck, oracle, (info) => !isLand(info.type_line) && youCreateCreatureToken(info.oracle_text));
    const anthems = countWhere(deck, oracle, (info) => !isLand(info.type_line) && isAnthem(info.oracle_text));
    return {
      token_makers: makers.copies,
      anthems: anthems.copies,
      _names: { makers: makers.names, anthems: anthems.names },
    };
  },
  "orzhov-auras"(deck, oracle) {
    const auras = countWhere(deck, oracle, (info) => String(info.type_line).includes("Aura"));
    const equipment = countWhere(deck, oracle, (info) => String(info.type_line).includes("Equipment"));
    const shields = countWhere(deck, oracle, (info) => grantsProtection(info.oracle_text, info.keywords));
    return {
      aura_count: auras.copies,
      equipment_count: equipment.copies,
      protection_count: shields.copies,
      _names: { auras: auras.names, shields: shields.names },
    };
  },
  "virtue-and-valor"(deck, oracle) {
    const auras = countWhere(deck, oracle, (info) => String(info.type_line).includes("Aura"));
    const creatureAuras = countWhere(deck, oracle, (info) => isCreatureAura(info.oracle_text, info.type_line));
    const landAuras = countWhere(deck, oracle, (info) => String(info.type_line).includes("Aura") && /enchant (?:forest|land)\b/i.test(stripReminder(info.oracle_text)));
    const equipment = countWhere(deck, oracle, (info) => String(info.type_line).includes("Equipment"));
    const shields = countWhere(deck, oracle, (info) => grantsProtection(info.oracle_text, info.keywords));
    return {
      aura_count: auras.copies,
      creature_aura_count: creatureAuras.copies,
      land_aura_count: landAuras.copies,
      equipment_count: equipment.copies,
      protection_count: shields.copies,
      _names: { auras: auras.names, creatureAuras: creatureAuras.names, landAuras: landAuras.names, shields: shields.names },
    };
  },
  "arcane-maelstrom": spellRole,
  "prismari-performance": spellRole,
  "seize-control": spellRole,
  "dimir-control"(deck, oracle) {
    const spells = spellRole(deck, oracle);
    const creatures = countWhere(deck, oracle, (info) => primary(info.type_line) === "Creature");
    return { ...spells, creature_count: creatures.copies, _names: { ...spells._names, creatures: creatures.names } };
  },
  "revenant-recon"(deck, oracle) {
    const spells = countWhere(deck, oracle, (info) => isReanimationSpell(info.oracle_text, info.type_line));
    const big = countWhere(deck, oracle, (info) => primary(info.type_line) === "Creature" && Number(info.cmc) >= 6);
    const cheapest = Math.min(...big.names.map((line) => manaValue(oracle, line.replace(/^\d+ /, ""))));
    const reanimate = manaValue(oracle, "Reanimate");
    return {
      reanimate_mv: reanimate,
      animate_dead_mv: manaValue(oracle, "Animate Dead"),
      necromancy_mv: manaValue(oracle, "Necromancy"),
      creatures_mv_6_plus: big.copies,
      cheapest_big_creature_mv: cheapest,
      reanimate_gap: cheapest - reanimate,
      _names: { spells: spells.names, big: big.names },
    };
  },
  "plunder-the-graves"(deck, oracle) {
    const big = countWhere(deck, oracle, (info) => primary(info.type_line) === "Creature" && Number(info.cmc) >= 6);
    const cheapest = Math.min(...big.names.map((line) => manaValue(oracle, line.replace(/^\d+ /, ""))));
    const servitude = manaValue(oracle, "Diabolic Servitude");
    return {
      diabolic_servitude_mv: servitude,
      rise_from_the_grave_mv: manaValue(oracle, "Rise from the Grave"),
      creatures_mv_6_plus: big.copies,
      cheapest_big_creature_mv: cheapest,
      servitude_gap: cheapest - servitude,
      _names: { big: big.names },
    };
  },
  "lands-wrath"(deck, oracle, facts) {
    return rampRole(deck, oracle, facts);
  },
  "veloci-ramp-tor"(deck, oracle, facts) {
    return rampRole(deck, oracle, facts);
  },
  "blood-rites"(deck, oracle) {
    const outlets = countWhere(deck, oracle, (info) => isSacrificeOutlet(info.oracle_text));
    const deaths = countWhere(deck, oracle, (info) => isDeathPayoff(info.oracle_text, info.type_line));
    const makers = countWhere(deck, oracle, (info) => !isLand(info.type_line) && youCreateCreatureToken(info.oracle_text));
    return {
      sacrifice_outlets: outlets.copies,
      death_payoffs: deaths.copies,
      token_makers: makers.copies,
      _names: { outlets: outlets.names, deaths: deaths.names, makers: makers.names },
    };
  },
  "lotus-field"(deck, oracle) {
    const big = countWhere(deck, oracle, (info) => !isLand(info.type_line) && Number(info.cmc) >= 7);
    const peer = countWhere(deck, oracle, (_info, card) => card.name === "Peer into the Abyss");
    const dig = countWhere(deck, oracle, (_info, card) => card.name === "Dig Through Time");
    return {
      nonland_mv_7_plus: big.copies,
      peer_copies: peer.copies,
      peer_mv: manaValue(oracle, "Peer into the Abyss"),
      dig_copies: dig.copies,
      _names: { big: big.names },
    };
  },
  "gruul-stompy"(deck, oracle) {
    const creatures = countWhere(deck, oracle, (info) => primary(info.type_line) === "Creature");
    const small = countWhere(deck, oracle, (info) => primary(info.type_line) === "Creature" && Number(info.cmc) <= 2);
    return {
      creature_count: creatures.copies,
      creatures_mv_2_or_less: small.copies,
      creatures_above_2: creatures.copies - small.copies,
      _names: { creatures: creatures.names, small: small.names },
    };
  },
  "orzhov-humans"(deck, oracle) {
    const creatures = countWhere(deck, oracle, (info) => primary(info.type_line) === "Creature");
    const small = countWhere(deck, oracle, (info) => primary(info.type_line) === "Creature" && Number(info.cmc) <= 2);
    return {
      creature_count: creatures.copies,
      creatures_mv_2_or_less: small.copies,
      creatures_above_2: creatures.copies - small.copies,
    };
  },
  "azorius-spirits"(deck, oracle) {
    const creatures = countWhere(deck, oracle, (info) => primary(info.type_line) === "Creature");
    const small = countWhere(deck, oracle, (info) => primary(info.type_line) === "Creature" && Number(info.cmc) <= 2);
    const answers = countWhere(deck, oracle, (info) => countersOrExilesSpell(info.oracle_text));
    return {
      creature_count: creatures.copies,
      creatures_mv_2_or_less: small.copies,
      spell_answers: answers.copies,
      _names: { answers: answers.names },
    };
  },
  "izzet-phoenix"(deck, oracle) {
    const spells = spellRole(deck, oracle);
    const creatures = countWhere(deck, oracle, (info) => primary(info.type_line) === "Creature");
    const small = countWhere(deck, oracle, (info) => primary(info.type_line) === "Creature" && Number(info.cmc) <= 2);
    return {
      instant_count: spells.instant_count,
      sorcery_count: spells.sorcery_count,
      instant_or_sorcery: spells.instant_or_sorcery,
      counter_target_count: spells.counter_target_count,
      creature_count: creatures.copies,
      creatures_mv_2_or_less: small.copies,
      _names: spells._names,
    };
  },
  "mono-red-burn"(deck, oracle) {
    let damage = 0;
    let copies = 0;
    const names = [];
    for (const card of rowsOf(deck)) {
      const info = infoOf(oracle, card.name);
      if (!isSpell(info.type_line)) continue;
      const text = stripReminder(info.oracle_text);
      if (!/any target|target player|each opponent/i.test(text)) continue;
      const amounts = [...text.matchAll(/deals (\d+) damage/gi)].map((match) => Number(match[1]));
      if (!amounts.length) continue;
      const each = amounts.reduce((sum, value) => sum + value, 0);
      damage += each * card.quantity;
      copies += card.quantity;
      names.push(`${card.quantity} ${card.name} deals ${each}`);
    }
    return { face_burn_damage: damage, face_burn_copies: copies, burn_past_starting_life: damage - 20, _names: { burn: names } };
  },
};

export function roleCounts(oracle, decks, preconFacts) {
  const roles = {};
  const notes = {};
  for (const [id, build] of Object.entries(BUILDERS)) {
    const built = build(decks[id], oracle, preconFacts);
    const names = built._names ?? {};
    delete built._names;
    roles[id] = built;
    notes[id] = names;
  }
  return { roles, notes };
}

function publicRole(role) {
  return Object.fromEntries(Object.entries(role).filter(([key]) => key !== "_names"));
}

export function storedRolesMatch(decks, roles) {
  const problems = [];
  for (const [id, role] of Object.entries(roles)) {
    const stored = decks[id]?.analysis?.role;
    const left = JSON.stringify(stored ?? null);
    const right = JSON.stringify(publicRole(role));
    if (left !== right) problems.push(`${id}: stored ${left} computed ${right}`);
  }
  return problems;
}

function main() {
  const root = new URL("../src/data/", import.meta.url);
  const oracle = JSON.parse(fs.readFileSync(new URL("example-card-oracle.json", root), "utf8")).cards;
  const decks = JSON.parse(fs.readFileSync(new URL("example-decks.json", root), "utf8")).decks;
  const facts = JSON.parse(fs.readFileSync(new URL("precon_facts.json", root), "utf8"));
  const { roles, notes } = roleCounts(oracle, decks, facts);
  if (process.argv.includes("--write")) {
    const path = new URL("example-decks.json", root);
    const doc = JSON.parse(fs.readFileSync(path, "utf8"));
    for (const [id, role] of Object.entries(roles)) doc.decks[id].analysis.role = publicRole(role);
    fs.writeFileSync(path, `${JSON.stringify(doc)}\n`);
  }
  for (const [id, role] of Object.entries(roles)) {
    console.log(`\n${id} ${JSON.stringify(publicRole(role))}`);
    for (const [key, value] of Object.entries(notes[id] ?? {})) console.log(`  ${key}: ${value.join("; ")}`);
  }
}

if (process.argv[1] && process.argv[1].endsWith("archetype-roles.mjs")) main();
