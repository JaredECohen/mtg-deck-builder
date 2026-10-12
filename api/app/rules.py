"""Deck-construction rules shared by the validator, generator and repository.

These are rules-text facts (CR 100.2a, 201.2, 903.3), not heuristics, so they
live in one place. Before this module the validator, generator and optimizer
each kept their own copy and had drifted: snow basics were capped at four
copies and "any number" cards like Relentless Rats were rejected.
"""

from __future__ import annotations

import re

from app.models import CardRecord

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
