"""What job a sideboard card does, from its oracle text.

Shared by the sideboard builder (fill 15 slots across the matchup classes a
format needs answers for) and the game-plan writer (which matchups each
sideboard card comes in against).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.models import CardRecord


@dataclass(frozen=True)
class SideboardClass:
    key: str
    purpose: str
    # Opponent archetype shapes this card is brought in against.
    against: tuple[str, ...]
    pattern: re.Pattern[str]


SIDEBOARD_CLASSES: tuple[SideboardClass, ...] = (
    SideboardClass(
        "graveyard_hate",
        "Graveyard hate",
        ("graveyard / reanimator decks", "delve and escape decks"),
        re.compile(
            r"exile (target|all|each) (card|cards|player's graveyard|graveyard)[^.]*graveyard"
            r"|exile all cards from all graveyards|exile target player's graveyard"
            r"|cards in graveyards (can't|lose)|if a card or token would be put into a graveyard",
            re.IGNORECASE,
        ),
    ),
    SideboardClass(
        "artifact_enchantment_removal",
        "Artifact / enchantment removal",
        ("artifact decks", "enchantment and aura decks"),
        re.compile(
            r"(destroy|exile) target (artifact|enchantment|artifact or enchantment|noncreature permanent)"
            r"|destroy all artifacts|destroy up to \w+ target artifacts",
            re.IGNORECASE,
        ),
    ),
    SideboardClass(
        "counterspell",
        "Counter magic",
        ("combo decks", "control decks", "big-spell ramp"),
        re.compile(r"counter target (noncreature |instant or sorcery |instant |sorcery |activated |)spell", re.IGNORECASE),
    ),
    SideboardClass(
        "sweeper",
        "Board wipe",
        ("go-wide aggro", "token decks"),
        re.compile(
            r"(destroy|exile) all (creatures|nonland permanents)|deals \d+ damage to each creature"
            r"|all creatures get -\d+/-\d+|each creature gets -\d+/-\d+",
            re.IGNORECASE,
        ),
    ),
    SideboardClass(
        "hand_disruption",
        "Hand disruption",
        ("combo decks", "control decks"),
        re.compile(r"target (player|opponent) reveals (his or her|their) hand", re.IGNORECASE),
    ),
    SideboardClass(
        "lifegain",
        "Lifegain against burn",
        ("burn", "red aggro"),
        re.compile(r"you gain [3-9] life|you gain \w+ life for each", re.IGNORECASE),
    ),
    SideboardClass(
        "creature_removal",
        "Creature removal",
        ("creature aggro", "midrange"),
        re.compile(
            r"(destroy|exile) target creature|deals \d+ damage to target creature"
            r"|target creature gets -\d+/-\d+|fights? target creature",
            re.IGNORECASE,
        ),
    ),
)

_BY_KEY = {cls.key: cls for cls in SIDEBOARD_CLASSES}


def classify(card: CardRecord) -> SideboardClass | None:
    """First matching class, in the order above (more specific first)."""
    text = card.oracle_text or " ".join(face.oracle_text or "" for face in card.faces)
    for cls in SIDEBOARD_CLASSES:
        if cls.pattern.search(text):
            return cls
    return None


def by_key(key: str) -> SideboardClass:
    return _BY_KEY[key]
