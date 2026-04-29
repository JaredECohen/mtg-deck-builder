from __future__ import annotations

# ── Deck sizes ────────────────────────────────────────────────────────────────
CONSTRUCTED_DECK_SIZE = 60
COMMANDER_DECK_SIZE = 99
SIDEBOARD_SIZE = 15
MAX_COPIES = 4  # maximum copies of a non-basic-land card in constructed

# ── Land targets ──────────────────────────────────────────────────────────────
LAND_TARGET_AGGRO = 22       # aggro / tempo / spellslinger
LAND_TARGET_DEFAULT = 24     # midrange / control / combo / fallback
LAND_TARGET_RAMP = 25        # ramp archetypes
LAND_TARGET_COMMANDER = 37   # commander mainboard

CONSTRUCTED_LAND_RANGE = (21, 27)   # (min, max) for validation warnings
COMMANDER_LAND_RANGE = (35, 40)     # (min, max) for validation warnings
COMMANDER_LAND_FLOOR = 35           # triggers extra warning when below this

# ── Tag → role bucket used by DeckValidator for scoring ──────────────────────
ROLE_TAGS: dict[str, str] = {
    "interaction": "interaction",
    "removal": "interaction",
    "countermagic": "interaction",
    "disruption": "interaction",
    "draw": "advantage",
    "cantrip": "advantage",
    "card_advantage": "advantage",
    "ramp": "ramp",
    "mana_rock": "ramp",
    "fixing": "ramp",
    "creature": "threat",
    "pressure": "threat",
    "finisher": "threat",
    "prowess": "payoff",
    "tokens": "payoff",
    "lifegain": "payoff",
    "graveyard": "engine",
    "spells": "engine",
    "tribal": "engine",
    "artifact": "engine",
}

# ── Tag → display role used by DeckGenerator for section labels ───────────────
ROLE_MAP: dict[str, str] = {
    "interaction": "interaction",
    "removal": "interaction",
    "countermagic": "interaction",
    "disruption": "interaction",
    "draw": "card advantage",
    "cantrip": "card advantage",
    "ramp": "mana development",
    "mana_rock": "mana development",
    "creature": "threat",
    "pressure": "threat",
    "finisher": "threat",
    "prowess": "payoff",
    "tokens": "payoff",
    "lifegain": "payoff",
    "graveyard": "engine",
    "spells": "engine",
    "tribal": "engine",
    "artifact": "engine",
    "land": "mana base",
}

# ── Tag canonicalization (alias → canonical tag) ──────────────────────────────
CANONICAL_TAGS: dict[str, str] = {
    "aggressive": "aggro",
    "aristocrats": "sacrifice",
    "artifacts": "artifact",
    "creatures": "creature",
    "life gain": "lifegain",
    "midrange": "midrange",
    "reanimator": "graveyard",
    "sacrifice": "sacrifice",
    "spellslinger": "spells",
    "tempo": "tempo",
    "tribal": "tribal",
}

# ── Theme → tag expansion used by DeckGenerator for strategy matching ─────────
THEME_TO_TAGS: dict[str, set[str]] = {
    "aggro": {"pressure", "creature"},
    "control": {"interaction", "draw"},
    "midrange": {"creature", "interaction"},
    "combo": {"engine", "graveyard", "spells"},
    "tempo": {"interaction", "spells", "pressure"},
    "ramp": {"ramp", "payoff"},
    "spells": {"spells", "prowess"},
    "tokens": {"tokens", "payoff"},
    "tribal": {"tribal", "creature"},
    "lifegain": {"lifegain", "payoff"},
    "graveyard": {"graveyard", "engine"},
    "sacrifice": {"engine", "payoff"},
}

# ── Role targets for Commander mainboard assembly ─────────────────────────────
COMMANDER_ROLE_TARGETS: dict[str, int] = {
    "ramp": 10,
    "draw": 10,
    "interaction": 10,
    "engine": 14,
    "payoff": 12,
}
