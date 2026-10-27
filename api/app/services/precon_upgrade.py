"""Upgrade a Commander precon in place, on a budget.

The user picks an official precon (or pastes a list) and a dollar amount.
The result is a ranked set of one-for-one swaps: a card that leaves, a card
that replaces it, why, and a TCGplayer cart for the adds. The total price of
the adds stays within the budget. Basics and the commander are not cut, so
the deck stays the same size.

Scoring is deterministic and uses the cards we already have: color identity,
Commander legality, a role read of the rules text, type overlap with the
commander, and the stored price. It does not call an LLM and it does not
read EDHREC.
"""

from __future__ import annotations

import re
from functools import lru_cache

from app.services.affiliate import tcgplayer_mass_entry_url
from app.models import (
    BracketAssessment,
    CardRecord,
    CardRef,
    ParseDecklistRequest,
    PreconSummary,
    PreconSwap,
    PreconUpgradeRequest,
    PreconUpgradeResponse,
    ValidateDeckRequest,
)
from app.rules import is_basic_land, is_land_card
from app.scripts.ingest_official_decks import load_snapshot
from app.services.brackets import assess, bracket_data, is_extra_turn, is_mass_land_denial
from app.services.card_function import describe
from app.services.card_repository import CardRepository
from app.services.card_roles import primary_role
from app.services.deck_parser import DeckParserService
from app.services.deck_validator import DeckValidator


class PreconNotFound(LookupError):
    """The catalog has no precon with this id."""


# How many cards of each job a Commander deck wants. A gap here is the
# usual reason a precon upgrade exists: more ramp, more draw, more removal.
ROLE_TARGETS = {
    "mana development": 10,
    "card advantage": 10,
    "interaction": 8,
    "threat": 15,
}
# A swap has to be a real improvement, not a sideways trade.
MIN_RAW_GAIN = 0.8
# Dollars below this tie. Otherwise a $0.05 card with the same job as a
# $1 mana rock wins on density and the upgrade list fills with junk.
PRICE_FLOOR = 1.0
_FUNCTIONAL = {"mana development", "card advantage", "interaction"}
_REMINDER = re.compile(r"\([^)]*\)")
# Tap, no extra cost. "{1}, {T}: Add" is a clunky rock and should not tie Sol Ring.
_ROCK = re.compile(
    r"(?:^|\n)\{T\}: Add (?:\{|one mana|two mana|three mana)",
    re.IGNORECASE,
)
_MULTI_MANA = re.compile(
    r"(?:^|\n)\{T\}: Add (?:\{[WUBRGC]\}\{|two mana|three mana)",
    re.IGNORECASE,
)
_TAPPED = re.compile(r"enters tapped|enters the battlefield tapped", re.IGNORECASE)


@lru_cache(maxsize=1)
def catalog() -> tuple[dict, ...]:
    return tuple(load_snapshot())


def clear_catalog_cache() -> None:
    catalog.cache_clear()


def _summary(record: dict) -> PreconSummary:
    commanders = [name for name in record.get("commanders") or [] if name]
    return PreconSummary(
        id=str(record["id"]),
        name=str(record["name"]),
        commander=commanders[0] if commanders else None,
        commanders=commanders,
        color_identity=list(record.get("color_identity") or []),
        release_date=record.get("release_date"),
        set_code=record.get("set_code"),
        format="commander",
    )


def search_precons(query: str = "", limit: int = 20) -> list[PreconSummary]:
    decks = [record for record in catalog() if record.get("format") == "commander"]
    needle = query.strip().lower()
    if needle:
        def matches(record: dict) -> bool:
            haystack = " ".join(
                [
                    str(record.get("name") or ""),
                    " ".join(record.get("commanders") or []),
                    str(record.get("set_code") or ""),
                ]
            ).lower()
            return needle in haystack

        decks = [record for record in decks if matches(record)]
    decks.sort(key=lambda record: (str(record.get("release_date") or ""), str(record.get("name") or "")), reverse=True)
    return [_summary(record) for record in decks[:limit]]


def _find_precon(precon_id: str) -> dict:
    for record in catalog():
        if record.get("id") == precon_id and record.get("format") == "commander":
            return record
    raise PreconNotFound(f"No precon with id {precon_id!r}. Search /v1/commander/precons.")


def _ordered_subtypes(card: CardRecord) -> list[str]:
    face = (card.type_line or "").split(" // ", 1)[0]
    if "—" not in face:
        return []
    right = face.split("—", 1)[1]
    return [part.strip().lower() for part in right.split() if part.strip()]


def _theme(commander: CardRecord | None, cards: list[CardRecord]) -> tuple[set[str], set[str]]:
    """Creature types that define the deck.

    The commander's first subtype (Goblin, for Krenko) is the tribe that
    matters. Later subtypes (Warrior) and types that show up three or more
    times are a weaker echo. Strategy tags such as "tokens" are not a theme:
    they match almost every recent red card and bury a mana rock under a
    $0.20 spell. Basic lands are not a theme either.
    """
    ordered = _ordered_subtypes(commander) if commander is not None else []
    strong = set(ordered[:1])
    weak = set(ordered[1:])
    counts: dict[str, int] = {}
    for card in cards:
        if is_land_card(card) or is_basic_land(card):
            continue
        if commander is not None and card.name == commander.name:
            continue
        for subtype in _ordered_subtypes(card):
            counts[subtype] = counts.get(subtype, 0) + 1
    weak |= {name for name, count in counts.items() if count >= 3} - strong
    return strong, weak


def _rules_text(card: CardRecord) -> str:
    text = card.oracle_text or ""
    return _REMINDER.sub("", text)


def _mentions(card: CardRecord, words: set[str]) -> bool:
    if not words:
        return False
    haystack = f"{card.name} {_rules_text(card)}"
    return any(re.search(rf"\b{re.escape(word)}\b", haystack, re.IGNORECASE) for word in words)


def _is_mana_rock(card: CardRecord) -> bool:
    type_line = card.type_line or ""
    if "Artifact" not in type_line or "Creature" in type_line or "Land" in type_line:
        return False
    return _ROCK.search(_rules_text(card)) is not None


def _hits(card: CardRecord, theme: tuple[set[str], set[str]]) -> int:
    strong, weak = theme
    subtypes = set(_ordered_subtypes(card))
    return len(strong & subtypes) + len(weak & subtypes)


def _role_counts(cards: list[CardRecord]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for card in cards:
        if is_land_card(card):
            continue
        role = primary_role(card)
        counts[role] = counts.get(role, 0) + 1
    return counts


def upgrade_value(
    card: CardRecord,
    *,
    theme: tuple[set[str], set[str]],
    role_counts: dict[str, int],
    land_count: int,
    protected: set[str],
) -> float:
    """Higher means the deck would rather keep (or add) this card."""
    if card.name in protected or is_basic_land(card):
        return 100.0
    strong, _weak = theme
    role = primary_role(card)
    subtypes = set(_ordered_subtypes(card))
    strong_hits = len(strong & subtypes)
    weak_hits = len(theme[1] & subtypes)
    text = _rules_text(card)
    raw = 1.0 + min(3.0, 2.2 * strong_hits + 0.4 * weak_hits)
    if _mentions(card, strong):
        raw += 3.0
    target = ROLE_TARGETS.get(role)
    if target is not None:
        have = role_counts.get(role, 0)
        gap = target - have
        if gap > 0:
            if have == 0 and role in _FUNCTIONAL:
                raw += 4.5
            elif have < target / 2:
                raw += 2.2
            else:
                raw += 0.8
        elif gap < -2:
            raw -= min(3.0, 0.4 * (-gap - 2))
    if _is_mana_rock(card) and role_counts.get("mana development", 0) < 6:
        raw += 3.5
        if _MULTI_MANA.search(text):
            raw += 1.5
    if role in _FUNCTIONAL and card.mana_value <= 2:
        raw += 1.0
    if (
        card.mana_value >= 6
        and role == "threat"
        and strong_hits == 0
        and not _mentions(card, strong)
    ):
        raw -= 3.0
    if is_land_card(card):
        if land_count >= 38:
            raw -= 3.0
        elif land_count <= 33:
            raw += 1.5
        if _TAPPED.search(text) and "search your library" not in text.lower():
            raw -= 2.0
    return raw


def _sentence(card: CardRecord) -> str:
    phrase = describe(card)
    if phrase:
        return f"{card.name} {phrase}."
    role = primary_role(card)
    mana = int(card.mana_value) if card.mana_value == int(card.mana_value) else card.mana_value
    return f"{card.name} is a {mana}-mana {role}."


def _cut_explanation(card: CardRecord, commander_name: str, theme: tuple[set[str], set[str]]) -> str:
    reasons: list[str] = []
    if _hits(card, theme) == 0 and not is_land_card(card):
        reasons.append(f"it doesn't share a type or theme with {commander_name}")
    if card.mana_value >= 6 and primary_role(card) == "threat" and _hits(card, theme) == 0:
        reasons.append("an expensive creature is the usual first cut from a precon")
    text = card.oracle_text or ""
    if is_land_card(card) and _TAPPED.search(text):
        reasons.append("it enters tapped, which is slow mana in a multiplayer game")
    if not reasons:
        reasons.append("the card coming in does that job better for this commander")
    return f"{_sentence(card)} Cut it because {reasons[0]}."


def _add_explanation(card: CardRecord, commander_name: str, theme: tuple[set[str], set[str]], role_counts: dict[str, int]) -> str:
    role = primary_role(card)
    reasons: list[str] = []
    target = ROLE_TARGETS.get(role)
    if target is not None and role_counts.get(role, 0) < target:
        reasons.append(f"the deck is short on {role}")
    if _is_mana_rock(card):
        reasons.append("it adds mana every turn, which a precon is usually short of")
    matched = sorted((theme[0] | theme[1]) & set(_ordered_subtypes(card)))
    if not matched and _mentions(card, theme[0]):
        matched = sorted(theme[0])
    if matched:
        shown = ", ".join(matched[:3])
        reasons.append(f"it lines up with {commander_name}'s {shown}")
    price = card.price_usd or 0.0
    reasons.append(f"it costs ${price:.2f}")
    return f"{_sentence(card)} Add it because {reasons[0]}, and {reasons[1]}." if len(reasons) > 1 else f"{_sentence(card)} Add it because {reasons[0]}."


def _identity(commanders: list[CardRecord], stored: list[str]) -> set[str]:
    if commanders:
        colors: set[str] = set()
        for card in commanders:
            colors.update(card.color_identity or card.colors)
        return {color for color in colors if color in {"W", "U", "B", "R", "G"}}
    return {color for color in stored if color in {"W", "U", "B", "R", "G"}}


def _blocked(
    card: CardRecord,
    *,
    max_bracket: int | None,
    game_changers_left: int,
    present: set[str],
) -> bool:
    if max_bracket is None or max_bracket >= 4:
        return False
    if is_mass_land_denial(card) or is_extra_turn(card):
        return True
    if card.name in bracket_data()["game_changers"] and (max_bracket <= 2 or game_changers_left <= 0):
        return True
    for pair in bracket_data()["two_card_combos"]:
        if card.name in pair and set(pair) - {card.name} <= present:
            return True
    return False


def _resolve(request: PreconUpgradeRequest, repository: CardRepository) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    text = (request.deck_text or "").strip()
    if text:
        parsed = DeckParserService(repository).parse(ParseDecklistRequest(format="commander", deck_text=text))
        warnings.extend(parsed.warnings)
        if not parsed.commander:
            raise ValueError("Paste a commander, or start the list with a Commander: line.")
        return {
            "id": None,
            "name": parsed.commander,
            "commanders": [parsed.commander],
            "color_identity": [],
            "mainboard": [ref.model_dump() for ref in parsed.mainboard],
        }, warnings
    if request.precon_id:
        return _find_precon(request.precon_id), warnings
    raise ValueError("Choose a precon or paste a decklist.")


def _apply(mainboard: list[CardRef], swaps: list[tuple[str, str]]) -> list[CardRef]:
    counts = {ref.name: ref.quantity for ref in mainboard}
    for cut, add in swaps:
        counts[cut] = counts.get(cut, 0) - 1
        if counts[cut] <= 0:
            counts.pop(cut, None)
        counts[add] = counts.get(add, 0) + 1
    return [CardRef(name=name, quantity=quantity) for name, quantity in sorted(counts.items())]


def upgrade_precon(
    request: PreconUpgradeRequest,
    *,
    repository: CardRepository,
    validator: DeckValidator,
) -> PreconUpgradeResponse:
    record, warnings = _resolve(request, repository)
    commander_names = [name for name in record.get("commanders") or [] if name]
    if not commander_names:
        raise ValueError("This list has no commander.")
    commander_cards = [card for name in commander_names if (card := repository.get_card(name)) is not None]
    if not commander_cards:
        raise ValueError(f"Unknown commander: {commander_names[0]}.")
    if len(commander_names) > 1:
        warnings.append(
            "This precon has more than one commander. Upgrades use both color identities; "
            "the legality check is against the first commander, so a partner list can report a deck-size miss."
        )
    missing = [name for name in commander_names if repository.get_card(name) is None]
    if missing:
        warnings.append("Couldn't find " + ", ".join(missing) + " in the card database.")

    identity = _identity(commander_cards, list(record.get("color_identity") or []))
    protected = set(commander_names)
    main_refs = [CardRef(name=str(card["name"]), quantity=int(card["quantity"])) for card in record.get("mainboard") or []]
    deck_cards: list[CardRecord] = []
    unknown = 0
    for ref in main_refs:
        card = repository.get_card(ref.name)
        if card is None:
            unknown += 1
            continue
        deck_cards.extend([card] * ref.quantity)
    if unknown:
        warnings.append(f"{unknown} card name{'s' if unknown != 1 else ''} in the list didn't match the database and can't be swapped.")

    present = {card.name for card in deck_cards} | protected
    theme = _theme(commander_cards[0], deck_cards)
    role_counts = _role_counts(deck_cards)
    land_count = sum(1 for card in deck_cards if is_land_card(card))
    budget = float(request.budget_usd)
    max_bracket = request.max_bracket
    game_changers_left = 3
    if max_bracket == 3:
        already = sum(1 for name in present if name in bracket_data()["game_changers"])
        game_changers_left = max(0, 3 - already)

    def value(card: CardRecord) -> float:
        return upgrade_value(
            card,
            theme=theme,
            role_counts=role_counts,
            land_count=land_count,
            protected=protected,
        )

    cuts = [card for card in {c.name: c for c in deck_cards}.values() if card.name not in protected and not is_basic_land(card)]
    pool: list[CardRecord] = []
    for card in repository.list_cards_for_format("commander"):
        if card.name in present or is_basic_land(card):
            continue
        if "Token" in (card.type_line or ""):
            continue
        if not repository.fits_color_identity(card, identity):
            continue
        if card.price_usd is None or card.price_usd < 0 or card.price_usd > budget:
            continue
        pool.append(card)
    pool.sort(key=lambda card: (-value(card), card.name))
    pool = pool[:400]

    swaps: list[PreconSwap] = []
    used_cuts: set[str] = set()
    used_adds: set[str] = set()
    remaining = budget
    while len(swaps) < request.max_swaps and remaining > 0 and cuts and pool:
        best: tuple[float, float, CardRecord, CardRecord] | None = None
        for cut in cuts:
            if cut.name in used_cuts:
                continue
            cut_value = value(cut)
            for add in pool:
                if add.name in used_adds:
                    continue
                price = float(add.price_usd or 0.0)
                if price > remaining + 1e-9:
                    continue
                if _blocked(add, max_bracket=max_bracket, game_changers_left=game_changers_left, present=present):
                    continue
                raw_gain = value(add) - cut_value
                if raw_gain < MIN_RAW_GAIN:
                    continue
                density = raw_gain / max(price, PRICE_FLOOR)
                better = best is None or density > best[0] + 1e-9
                tied = best is not None and abs(density - best[0]) <= 1e-9 and (
                    raw_gain > best[1] or (abs(raw_gain - best[1]) <= 1e-9 and add.name < best[2].name)
                )
                if better or tied:
                    best = (density, raw_gain, add, cut)
        if best is None:
            break
        _density, raw_gain, add, cut = best
        price = round(float(add.price_usd or 0.0), 2)
        swaps.append(PreconSwap(
            rank=len(swaps) + 1,
            cut=cut.name,
            cut_explanation=_cut_explanation(cut, commander_cards[0].name, theme),
            add=add.name,
            add_explanation=_add_explanation(add, commander_cards[0].name, theme, role_counts),
            add_price_usd=price,
            score=round(raw_gain, 3),
        ))
        used_cuts.add(cut.name)
        used_adds.add(add.name)
        remaining -= price
        present.add(add.name)
        if add.name in bracket_data()["game_changers"]:
            game_changers_left -= 1
        if not is_land_card(cut):
            role_counts[primary_role(cut)] = max(0, role_counts.get(primary_role(cut), 0) - 1)
        if not is_land_card(add):
            role_counts[primary_role(add)] = role_counts.get(primary_role(add), 0) + 1
        if is_land_card(cut):
            land_count -= 1
        if is_land_card(add):
            land_count += 1

    swaps.sort(key=lambda swap: (-swap.score, swap.add))
    for rank, swap in enumerate(swaps, start=1):
        swap.rank = rank
    total = round(sum(swap.add_price_usd for swap in swaps), 2)
    total = round(total, 2)
    if total > budget + 0.001:
        # Defensive: the loop tracks `remaining`, so this is a rounding guard.
        while swaps and total > budget + 0.001:
            dropped = swaps.pop()
            total = round(total - dropped.add_price_usd, 2)
        for rank, swap in enumerate(swaps, start=1):
            swap.rank = rank

    upgraded = _apply(main_refs, [(swap.cut, swap.add) for swap in swaps])
    legality = validator.validate(ValidateDeckRequest(
        format="commander",
        commander=commander_cards[0].name,
        mainboard=upgraded,
    ))
    names = [card.name for card in commander_cards] + [ref.name for ref in upgraded]
    bracket: BracketAssessment = assess(names, repository, target=max_bracket)

    cart = tcgplayer_mass_entry_url((swap.add, 1) for swap in swaps) if swaps else None
    return PreconUpgradeResponse(
        precon_id=record.get("id"),
        name=str(record.get("name") or commander_cards[0].name),
        commander=commander_cards[0].name,
        commanders=commander_names,
        budget_usd=budget,
        total_cost_usd=total,
        swaps=swaps,
        legality=legality,
        bracket=bracket,
        tcgplayer_cart_url=cart,
        warnings=warnings,
        upgraded_mainboard=upgraded,
    )
