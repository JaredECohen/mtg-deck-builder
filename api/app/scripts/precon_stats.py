"""Counts and prices for an official product deck, from Scryfall oracle text.

These rules are the ones the Week 1 guides cite. A change here changes the
facts file and the guides have to be regenerated. Lands are the land count
only: a land that draws or ramps is not also a ramp, draw, or removal card.
Nonlands can match more than one of ramp, draw, and removal. Counts are
copies, not unique names.

Ramp (nonland) is a card that, on a sentence you control:
- adds mana ({T}: Add, Add {C}, "add one mana of any color", "add two/three/X mana"),
- searches your library for a land or basic land type and puts it onto the battlefield,
- lets you play an additional land or put a land from your hand onto the battlefield,
- or creates a Treasure you get.

A land search that replaces a card for its controller ("its controller may
search their library") is not ramp. Opponent-only Treasure creation is not ramp.

Draw (nonland) is a card that draws you cards ("you draw", "target player
draws", "each player draws", "you may draw") or exiles the top of your library
and lets you play or cast those cards. Reminder text, including cycling's
"draw a card", is ignored. A sentence that only draws for an opponent is not
draw. "Whenever you draw a card, ..." is a trigger, not a draw effect, so
Psychosis Crawler, Smothering Tithe, and Ominous Seas do not count.

Removal (nonland) is a card that destroys or exiles an opponent's permanent,
deals damage to a creature or any target, gives a target creature -N/-N, gives
all creatures or each creature -N/-N, fights, forces a sacrifice, or shuffles
a permanent into a library. Counterspells are not removal. Exiling your own
permanents and bringing them back (blink) is not removal.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable

_MANA_ABILITY = re.compile(
    r"\{T\}(?::|,)[^.]{0,120}?\bAdd\b"
    r"|\bAdd \{[WUBRGC]"
    r"|\bAdd one mana of any color"
    r"|\bAdd two mana\b"
    r"|\bAdd three mana\b"
    r"|\bAdd X mana\b",
    re.IGNORECASE,
)
_LAND_WORD = re.compile(r"\b(?:land|forest|plains|island|swamp|mountain|wastes|gate)s?\b", re.IGNORECASE)
_YOUR_LAND_SEARCH = re.compile(r"search your library for", re.IGNORECASE)
_OPPONENT_CLAUSE = re.compile(r"\b(?:its controller|that player|opponents?)\b", re.IGNORECASE)
_EXTRA_LAND = re.compile(
    r"you may play an additional land"
    r"|put (?:a|an|up to \w+|one|two|three) land cards?(?: from your hand)? onto the battlefield",
    re.IGNORECASE,
)
_TREASURE = re.compile(r"\bcreat(?:e|es)\b[^.]{0,40}\btreasure\b", re.IGNORECASE)
_DRAW = re.compile(
    r"\bdraws? (?:a|an|one|two|three|four|five|six|seven|X|\d+) cards?\b"
    r"|\bdraw cards equal to\b"
    r"|\byou may draw\b",
    re.IGNORECASE,
)
_YOU_DRAW = re.compile(r"\byou\b|\btarget player\b|\beach player\b", re.IGNORECASE)
_OPPONENT_DRAW = re.compile(r"\bopponents?\b", re.IGNORECASE)
_IMPULSE = re.compile(
    r"exile the top \S+(?: \S+){0,8} cards? of your library\b[^.]*\byou may (?:play|cast)\b",
    re.IGNORECASE,
)
_REMOVAL = re.compile(
    r"\bdestroy (?:target|all|each) (?!card\b)(?:creature|permanent|artifact|enchantment|planeswalker|nonland)s?\b(?!\s+card)"
    r"|\bexile (?:target|all|each) (?!card\b)(?:creature|permanent|artifact|enchantment|planeswalker|nonland)s?\b(?!\s+card)"
    r"|\bdeals? \d+ damage to (?:any target|target creature|target planeswalker|each creature)\b"
    r"|\bdamage to any target\b"
    r"|\ball creatures get -"
    r"|\beach creature gets -"
    r"|\btarget (?:creature|artifact creature) gets? -\d+/-"
    r"|\btarget creature gets? -[Xx]/-"
    r"|\bfights? target\b"
    r"|\btarget (?:player|opponent) sacrifices\b"
    r"|\beach opponent sacrifices\b"
    r"|\bshuffles? (?:it|that card|target permanent) into\b",
    re.IGNORECASE,
)
_YOU_CONTROL = re.compile(r"\byou control\b", re.IGNORECASE)
TOKEN_LAYOUTS = {"token", "double_faced_token", "emblem", "art_series"}
EXCLUDED_PRICE_SET_TYPES = {"memorabilia", "token"}


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"[.\n]", text or "") if part.strip()]


def strip_reminder(text: str) -> str:
    """Drop parenthetical reminder text. Cycling's draw lives there."""
    kept: list[str] = []
    depth = 0
    for char in text or "":
        if char == "(":
            depth += 1
            continue
        if char == ")" and depth:
            depth -= 1
            continue
        if depth == 0:
            kept.append(char)
    return "".join(kept)


def is_bulk_token(card: dict) -> bool:
    """A Scryfall row that is a token or emblem, not the card that shares its name."""
    if str(card.get("layout") or "") in TOKEN_LAYOUTS:
        return True
    return card.get("set_type") == "token"


def is_price_printing(card: dict) -> bool:
    """English paper printing that can supply a retail nonfoil or foil price.

    Gold-bordered World Championship copies, oversized cards, memorabilia, and
    tokens are not the price of a sleeveable card.
    """
    if card.get("lang") != "en":
        return False
    games = card.get("games") or []
    if "paper" not in games:
        return False
    if card.get("set_type") in EXCLUDED_PRICE_SET_TYPES:
        return False
    if card.get("border_color") == "gold":
        return False
    if card.get("oversized") is True:
        return False
    return not is_bulk_token(card)


def _draw_trigger_only(sentence: str) -> bool:
    """True when the only draw is the 'whenever someone draws' trigger."""
    head, separator, tail = sentence.partition(",")
    if not separator:
        return False
    if not re.match(r"^whenever\b", head.strip(), re.IGNORECASE):
        return False
    if not re.search(r"\bdraws?\b", head, re.IGNORECASE):
        return False
    return _DRAW.search(tail) is None


def is_land_type(type_line: str) -> bool:
    """True when the front face's types include Land."""
    face = (type_line or "").split("//", 1)[0]
    types = face.split("—", 1)[0].split("–", 1)[0]
    return "Land" in types.split()


def is_ramp(type_line: str, oracle_text: str) -> bool:
    if is_land_type(type_line):
        return False
    for sentence in sentences(oracle_text):
        if _MANA_ABILITY.search(sentence):
            return True
        if _EXTRA_LAND.search(sentence):
            return True
        if _YOUR_LAND_SEARCH.search(sentence) and _LAND_WORD.search(sentence) and "battlefield" in sentence.lower():
            if not _OPPONENT_CLAUSE.search(sentence):
                return True
        if _TREASURE.search(sentence):
            low = sentence.lower()
            if "you" in low or _OPPONENT_CLAUSE.search(sentence) is None:
                return True
    return False


def is_draw(type_line: str, oracle_text: str) -> bool:
    if is_land_type(type_line):
        return False
    text = strip_reminder(oracle_text)
    parts = sentences(text)
    for index, sentence in enumerate(parts):
        if _draw_trigger_only(sentence):
            continue
        blob = sentence if index + 1 >= len(parts) else f"{sentence} {parts[index + 1]}"
        if _IMPULSE.search(blob):
            return True
        if not _DRAW.search(sentence):
            continue
        if _OPPONENT_DRAW.search(sentence) and not _YOU_DRAW.search(sentence):
            continue
        return True
    return False


def is_removal(type_line: str, oracle_text: str) -> bool:
    if is_land_type(type_line):
        return False
    text = strip_reminder(oracle_text)
    if not _REMOVAL.search(text):
        return False
    # Blink and "exile the creatures you control" are not removal.
    if re.search(r"\bexile\b", text, re.IGNORECASE) and _YOU_CONTROL.search(text):
        kept = [sentence for sentence in sentences(text) if not _YOU_CONTROL.search(sentence)]
        if not _REMOVAL.search(" ".join(kept)):
            return False
    return True


def parse_usd(value: object) -> float | None:
    """Scryfall bulk stores prices as strings. Null and blank are unpriced."""
    if value is None or value == "":
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def line_usd(price: float | None, quantity: int) -> float | None:
    if price is None or quantity <= 0:
        return None
    return round(price * quantity, 2)


def sum_usd(lines: Iterable[float | None]) -> float:
    return round(sum(line for line in lines if line is not None), 2)


def as_number(value: float) -> int | float:
    rounded = round(float(value), 4)
    if abs(rounded - round(rounded)) < 1e-9:
        return int(round(rounded))
    return rounded


def distribution(pairs: list[tuple[str, int | float]], *, ndigits: int = 1) -> dict:
    """min, max, mean, median, quartiles, and the three lowest and highest decks.

    Summary figures are rounded to ``ndigits`` so a guide can quote them
    without a second rounding step. The middle half uses those rounded bounds.
    """
    if not pairs:
        raise ValueError("distribution needs at least one deck")
    ordered = sorted(pairs, key=lambda item: (item[1], item[0]))
    values = [float(value) for _, value in ordered]
    quarters = statistics.quantiles(values, n=4, method="inclusive") if len(values) >= 2 else [values[0], values[0], values[0]]

    def rounded(value: float) -> int | float:
        return as_number(round(value, ndigits))

    p25 = rounded(quarters[0])
    p75 = rounded(quarters[2])
    middle = sum(1 for value in values if p25 <= value <= p75)
    return {
        "min": rounded(float(ordered[0][1])),
        "max": rounded(float(ordered[-1][1])),
        "mean": rounded(statistics.fmean(values)),
        "median": rounded(statistics.median(values)),
        "p25": p25,
        "p75": p75,
        "in_middle_half": middle,
        "in_middle_half_pct": round(100 * middle / len(values), 1),
        "lowest": [{"id": deck_id, "value": as_number(value)} for deck_id, value in ordered[:3]],
        "highest": [{"id": deck_id, "value": as_number(value)} for deck_id, value in reversed(ordered[-3:])],
    }
