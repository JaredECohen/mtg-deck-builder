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

_DRAW_TEXT = re.compile(r"draw (?:a|two|three|\w+) cards?|investigate|look at the top", re.IGNORECASE)
# Damage that can hit creatures is removal first; player-only damage is reach.
_REMOVAL_DAMAGE_TEXT = re.compile(r"damage to (?:any target|target creature|each creature)", re.IGNORECASE)
_REACH_TEXT = re.compile(r"damage to (?:target player|each opponent|target opponent)", re.IGNORECASE)
_RAMP_TEXT = re.compile(r"add \{|search your library for (?:a|up to \w+) (?:basic )?land", re.IGNORECASE)

# Tags that describe what a card is a part of, not what it does.
_TYPE_ONLY_TAGS = frozenset({"spells", "land", "creature", "artifact"})


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


def primary_role(card: CardRecord | None) -> str:
    if card is None:
        return "flex slot"
    if is_land_card(card):
        return "mana base"
    type_line = card.type_line or ""
    is_spell = "Instant" in type_line or "Sorcery" in type_line
    can_attack = "Creature" in type_line or "Planeswalker" in type_line
    for tag in card.tags:
        role = ROLE_MAP.get(tag)
        if role is None or tag in _TYPE_ONLY_TAGS:
            continue
        if role == "threat" and not can_attack:
            continue
        return role
    if can_attack:
        return "threat"
    if is_spell:
        return _spell_role(card)
    if "Artifact" in type_line or "Enchantment" in type_line:
        text = card.oracle_text or ""
        if _RAMP_TEXT.search(text):
            return "mana development"
        if _DRAW_TEXT.search(text):
            return "card advantage"
        return "engine"
    return "flex slot"
