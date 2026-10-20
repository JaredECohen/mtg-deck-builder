"""A card's primary job in a deck: threat, interaction, card advantage, ...

Shared by the generator and the analyzer (role summaries and the per-card
"Why?" notes). The ingest tags are coarse and sometimes wrong for the card's
type: every instant and sorcery carries "spells", Goblin Guide carries
"land" (its text mentions lands), and Ashnod's Altar carries "creature". So a
tag only sets the role when it agrees with the card's type, and instants and
sorceries are read from their oracle text.
"""

from __future__ import annotations

import re

from app.constants import ROLE_MAP
from app.models import CardRecord
from app.rules import is_land_card
from app.services.sideboard_classes import classify

# Includes impulse draw: exile the top cards, then you may play them
# (Light Up the Stage, Reckless Impulse).
_DRAW_TEXT = re.compile(
    r"draw (?:a|two|three|\w+) cards?|investigate|look at the top"
    r"|exile the top (?:\w+ )?cards? of your library[^.]*\.[^.]*you may (?:play|cast)",
    re.IGNORECASE,
)
# Damage that can hit creatures is removal first; player-only damage is reach.
_REMOVAL_DAMAGE_TEXT = re.compile(r"damage to (?:any target|target creature|each creature)", re.IGNORECASE)
_REACH_TEXT = re.compile(r"damage to (?:target player|each opponent|target opponent)", re.IGNORECASE)
_RAMP_TEXT = re.compile(r"add \{|add one mana|search your library for (?:a|up to \w+) (?:basic )?land", re.IGNORECASE)


def _spell_role(card: CardRecord) -> str:
    text = card.oracle_text or " ".join(face.oracle_text or "" for face in card.faces)
    if classify(card) is not None or _REMOVAL_DAMAGE_TEXT.search(text):
        return "interaction"
    if _REACH_TEXT.search(text):
        return "reach"
    if _DRAW_TEXT.search(text):
        return "card advantage"
    if _RAMP_TEXT.search(text):
        return "mana development"
    return "flex slot"


# Tags in priority order. The ingest stores tags in arbitrary order and many
# cards carry several (Force of Negation: graveyard, interaction, removal,
# spells), so the first tag on the card was a coin flip.
_TAG_PRIORITY = (
    "removal", "countermagic", "interaction", "disruption",
    "draw", "cantrip",
    "ramp", "mana_rock",
    "pressure", "finisher",
    "prowess", "tokens", "lifegain",
    "graveyard", "tribal",
)


def _role_from_tags(card: CardRecord, can_attack: bool) -> str | None:
    tags = set(card.tags)
    for tag in _TAG_PRIORITY:
        if tag not in tags:
            continue
        role = ROLE_MAP.get(tag)
        if role is None or (role == "threat" and not can_attack):
            continue
        return role
    return None


def primary_role(card: CardRecord | None) -> str:
    if card is None:
        return "flex slot"
    if is_land_card(card):
        return "mana base"
    type_line = card.type_line or ""
    text = card.oracle_text or " ".join(face.oracle_text or "" for face in card.faces)
    # A planeswalker is a threat even when one ability ramps or draws
    # (Chandra, Torch of Defiance).
    if "Planeswalker" in type_line:
        return "threat"
    # Instants and sorceries say what they do: trust the rules text first.
    if "Instant" in type_line or "Sorcery" in type_line:
        role = _spell_role(card)
        return role if role != "flex slot" else (_role_from_tags(card, can_attack=False) or role)
    if "Creature" in type_line:
        # Mana creatures (Llanowar Elves) are acceleration, not threats.
        if card.mana_value <= 3 and _RAMP_TEXT.search(text):
            return "mana development"
        role = _role_from_tags(card, can_attack=True)
        # An engine or payoff creature needs a triggered ability to be one;
        # Tarmogoyf's graveyard tag doesn't make it an engine.
        if role in {"engine", "payoff"} and "whenever" not in text.lower():
            role = None
        return role or "threat"
    role = _role_from_tags(card, can_attack=False)
    if role:
        return role
    if "Artifact" in type_line or "Enchantment" in type_line:
        if _RAMP_TEXT.search(text):
            return "mana development"
        if _DRAW_TEXT.search(text):
            return "card advantage"
        return "engine"
    return "flex slot"
