"""Deck-construction rules shared by the validator, generator and repository.

These are rules-text facts (CR 100.2a, 201.2, 903.3), not heuristics, so they
live in one place. Before this module the validator, generator and optimizer
each kept their own copy and had drifted: snow basics were capped at four
copies and "any number" cards like Relentless Rats were rejected.
"""

from __future__ import annotations

import re

from app.models import CardRecord

_BASIC_LAND_WORDS = (
    ("plains", "W"),
    ("island", "U"),
    ("swamp", "B"),
    ("mountain", "R"),
    ("forest", "G"),
)
_EXACT_BASIC_NAMES = {
    "plains",
    "island",
    "swamp",
    "mountain",
    "forest",
    "wastes",
    "snow-covered plains",
    "snow-covered island",
    "snow-covered swamp",
    "snow-covered mountain",
    "snow-covered forest",
}

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
_ANY_NUMBER = re.compile(r"a deck can have any number of cards named", re.IGNORECASE)
_UP_TO_N = re.compile(r"a deck can have up to (\w+) cards named", re.IGNORECASE)
_CAN_BE_COMMANDER = re.compile(r"can be your commander", re.IGNORECASE)


def front_face_type_line(type_line: str) -> str:
    return type_line.split(" // ", 1)[0]


def is_basic_type_line(type_line: str) -> bool:
    """True for any basic land, including snow basics and Wastes.

    "Basic" is a supertype, so it appears before the em dash alongside other
    supertypes: "Basic Land — Island", "Basic Snow Land — Island".
    """
    supertypes_and_types = front_face_type_line(type_line).split("—", 1)[0].split()
    return "Basic" in supertypes_and_types and "Land" in supertypes_and_types


def is_basic_land(card: CardRecord) -> bool:
    return is_basic_type_line(card.type_line)


def is_land_card(card: CardRecord) -> bool:
    """A card counts as a land when its front face is one.

    Spell//land modal double-faced cards ("Instant // Land") are spells for
    deck-building purposes: counting them as lands inflates the land count
    of a deck that runs them as spells.
    """
    return "Land" in front_face_type_line(card.type_line)


def copy_limit(card: CardRecord, format_name: str) -> int | None:
    """Maximum copies of ``card`` in a deck, or None for unlimited.

    Basic lands and "A deck can have any number of cards named …" are
    unlimited in every format, Commander included. "Up to seven cards named …"
    (Seven Dwarves, Nazgûl) caps at that number. Restricted cards and Commander
    singleton are 1; otherwise 4.
    """
    if is_basic_land(card):
        return None
    text = card.oracle_text or ""
    if _ANY_NUMBER.search(text):
        return None
    match = _UP_TO_N.search(text)
    if match:
        word = match.group(1).lower()
        limit = _NUMBER_WORDS.get(word) or (int(word) if word.isdigit() else None)
        if limit:
            return limit
    if format_name == "commander" or card.legalities.get(format_name) == "restricted":
        return 1
    return 4


def can_be_commander(card: CardRecord) -> bool:
    """CR 903.3: a legendary creature, or a card whose text says it can be your
    commander (some planeswalkers, e.g. Aminatou). For double-faced cards the
    front face decides.

    Format legality is a separate check (``legalities["commander"]``).
    """
    front = front_face_type_line(card.type_line)
    if "Legendary" in front and "Creature" in front:
        return True
    return bool(_CAN_BE_COMMANDER.search(card.oracle_text or ""))


def land_produced_colors(*, name: str, type_line: str = "", oracle_text: str = "") -> list[str]:
    """Colors a land can add, in WUBRG order.

    Basic lands are the case this exists for. Scryfall leaves their color
    identity empty, and the goldfish used to read only profile keywords, so a
    Mountain added colorless mana and never counted as a red source. Land types
    on the type line (and the card name, for "Mountain" / "Snow-Covered
    Mountain") are the source of those colors. Other lands use mana symbols in
    the oracle text. Lands that add "any color in your commander's color
    identity" are not treated as five-color sources; the caller decides which
    of the deck's colors they count as.
    """
    face = (type_line or "").split("//", 1)[0]
    lowered_face = face.lower()
    bare_name = (name or "").strip().lower()
    if "land" not in lowered_face and bare_name not in _EXACT_BASIC_NAMES:
        return []

    colors: list[str] = []

    def add(color: str) -> None:
        if color not in colors:
            colors.append(color)

    subtypes = face
    for dash in (" — ", " – ", " - "):
        if dash in face:
            subtypes = face.split(dash, 1)[1]
            break
    subtype_words = {word.strip(" ,.").lower() for word in re.split(r"[\s/]+", subtypes) if word.strip(" ,.")}
    for word, color in _BASIC_LAND_WORDS:
        if word in subtype_words:
            add(color)

    simple = bare_name.removeprefix("snow-covered ").strip()
    for word, color in _BASIC_LAND_WORDS:
        if simple == word:
            add(color)
    if colors:
        return colors

    text = oracle_text or ""
    lowered = text.lower()
    if "any color" in lowered and "commander" not in lowered:
        return ["W", "U", "B", "R", "G"]
    for symbol in re.findall(r"\{([WUBRG])\}", text):
        add(symbol)
    return colors


def count_color_sources(cards: list[dict]) -> dict[str, int]:
    """Count colored sources. ``produced_mana`` (Scryfall) wins when present.

    ``C`` is not a colored source. A land whose text adds mana of the
    commander's color identity counts for ``commander_colors`` only.
    """
    totals = {color: 0 for color in "WUBRG"}
    for card in cards:
        quantity = int(card.get("quantity") or 1)
        if quantity <= 0:
            continue
        oracle = str(card.get("oracle_text") or "")
        commander_colors = [c for c in (card.get("commander_colors") or []) if c in totals]
        if commander_colors and "commander" in oracle.lower() and "color identity" in oracle.lower():
            produced = commander_colors
        else:
            raw = card.get("produced_mana")
            if isinstance(raw, list) and raw:
                produced = [c for c in raw if c in totals]
            else:
                produced = land_produced_colors(
                    name=str(card.get("name") or ""),
                    type_line=str(card.get("type_line") or ""),
                    oracle_text=oracle,
                )
        for color in produced:
            totals[color] += quantity
    return totals
