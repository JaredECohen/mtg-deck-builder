"""Deterministic brief parsing: the no-LLM path for spec §11A.

When the Anthropic key is missing or the call fails, ``interpret_generate_prompt``
used to return an empty intent, so "a cheap mono-green stompy deck under $40"
came back as a colorless $578 Eldrazi deck. This parser recovers the
constraints a brief states outright: colors (words, guild/shard/wedge names,
"mono-X"), a budget, playstyle and theme keywords, and "no <card>" exclusions.
It deliberately does not guess card names to include — that needs the LLM.
"""

from __future__ import annotations

import re

# Two-, three- and four-color group names → WUBRG letters.
_COLOR_GROUPS: dict[str, str] = {
    "azorius": "WU", "dimir": "UB", "rakdos": "BR", "gruul": "RG", "selesnya": "GW",
    "orzhov": "WB", "izzet": "UR", "golgari": "BG", "boros": "RW", "simic": "GU",
    "bant": "GWU", "esper": "WUB", "grixis": "UBR", "jund": "BRG", "naya": "RGW",
    "abzan": "WBG", "jeskai": "URW", "sultai": "BGU", "mardu": "RWB", "temur": "GUR",
    "domain": "WUBRG", "five-color": "WUBRG", "5-color": "WUBRG", "4c": "",
}
_COLOR_WORDS: dict[str, str] = {
    "white": "W", "blue": "U", "black": "B", "red": "R", "green": "G",
}
_PLAYSTYLES: dict[str, str] = {
    "aggro": "aggro", "aggressive": "aggro", "burn": "aggro", "stompy": "aggro", "zoo": "aggro",
    "control": "control", "draw-go": "control",
    "midrange": "midrange", "value": "midrange",
    "combo": "combo", "storm": "combo",
    "tempo": "tempo", "flash": "tempo",
    "ramp": "ramp", "big mana": "ramp", "tron": "ramp",
    "spells": "spells", "spellslinger": "spells", "prowess": "spells",
    "tokens": "tokens", "go-wide": "tokens", "go wide": "tokens",
    "tribal": "tribal", "typal": "tribal",
    "lifegain": "lifegain", "life gain": "lifegain",
    "graveyard": "graveyard", "reanimator": "graveyard", "self-mill": "graveyard", "dredge": "graveyard",
    "sacrifice": "sacrifice", "aristocrats": "sacrifice",
}
# Mechanics and tribes kept as theme tags (also matched in tag vocab).
_THEMES = (
    "prowess", "storm", "slivers", "elves", "goblins", "merfolk", "zombies", "vampires", "dragons",
    "angels", "humans", "spirits", "wizards", "artifacts", "enchantments", "auras", "equipment",
    "counters", "+1/+1 counters", "landfall", "blink", "flicker", "mill", "infect", "energy", "affinity",
    "delirium", "cascade", "madness", "voltron", "stax", "superfriends", "planeswalkers",
)
_CHEAP_WORDS = re.compile(r"\b(cheap|budget|inexpensive|affordable|low[- ]cost)\b", re.IGNORECASE)
_BUDGET = re.compile(
    r"(?:under|below|less than|max(?:imum)?|budget(?: of)?|up to|around|about|<)\s*\$?\s*(\d{1,5}(?:\.\d+)?)"
    r"|\$\s*(\d{1,5}(?:\.\d+)?)"
    r"|(\d{1,5}(?:\.\d+)?)\s*(?:dollars|usd|bucks)",
    re.IGNORECASE,
)
_EXCLUDE = re.compile(r"\b(?:no|without|avoid|exclude|not)\s+([A-Z][\w',\- ]{2,40}?)(?=[,.;]|\s+(?:and|or|but)\b|$)")
# Budget used when a brief says "cheap" with no number.
CHEAP_DEFAULT_BUDGET = 60.0


def _word(pattern: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])" + re.escape(pattern) + r"s?(?![a-z0-9])", re.IGNORECASE)


def parse_brief(prompt: str) -> dict:
    """Return a dict shaped like ``GeneratePromptIntent``."""
    text = prompt or ""
    lowered = text.lower()
    colors: list[str] = []

    def add_colors(letters: str) -> None:
        for letter in letters:
            if letter not in colors:
                colors.append(letter)

    mono = re.search(r"mono[- ]?(white|blue|black|red|green)", lowered)
    if mono:
        add_colors(_COLOR_WORDS[mono.group(1)])
    else:
        for name, letters in _COLOR_GROUPS.items():
            if _word(name).search(lowered):
                add_colors(letters)
        for word, letter in _COLOR_WORDS.items():
            if _word(word).search(lowered):
                add_colors(letter)
        if re.search(r"\bcolou?rless\b|\beldrazi\b", lowered) and not colors:
            colors.append("C")

    playstyles: list[str] = []
    for keyword, tag in _PLAYSTYLES.items():
        if _word(keyword).search(lowered) and tag not in playstyles:
            playstyles.append(tag)
    themes = [theme for theme in _THEMES if _word(theme).search(lowered)]

    budget: float | None = None
    match = _BUDGET.search(text)
    if match:
        value = next(group for group in match.groups() if group)
        budget = float(value)
    elif _CHEAP_WORDS.search(text):
        budget = CHEAP_DEFAULT_BUDGET

    excludes = [m.group(1).strip() for m in _EXCLUDE.finditer(text)]
    return {
        "colors": colors,
        "playstyle_tags": playstyles,
        "theme_tags": themes,
        "budget": budget,
        "commander_name": None,
        "include_cards": [],
        "exclude_cards": excludes,
    }
