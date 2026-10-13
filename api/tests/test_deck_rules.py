"""Deck-construction rules (app/rules.py) and the validator that applies them.

Cards are built in-process so these run on any dataset, including CI's
29-card sample, which has no snow basics or "any number" cards.
"""

from __future__ import annotations

import pytest

from app.models import CardRecord, CardRef, ValidateDeckRequest
from app.rules import can_be_commander, copy_limit, is_basic_land
from app.services.card_repository import CardRepository
from app.services.deck_validator import DeckValidator

_ALL_LEGAL = {fmt: "legal" for fmt in ("standard", "pioneer", "modern", "legacy", "commander")}


def _card(name: str, type_line: str, oracle_text: str = "", colors: list[str] | None = None,
          legalities: dict[str, str] | None = None) -> CardRecord:
    colors = colors or []
    return CardRecord(
        name=name, type_line=type_line, oracle_text=oracle_text,
        colors=colors, color_identity=colors, legalities=legalities or dict(_ALL_LEGAL),
    )


CARDS = {
    card.name: card
    for card in [
        _card("Mountain", "Basic Land — Mountain", colors=[]),
        _card("Snow-Covered Mountain", "Basic Snow Land — Mountain"),
        _card("Wastes", "Basic Land"),
        _card("Lightning Bolt", "Instant", "Lightning Bolt deals 3 damage to any target.", ["R"]),
        _card("Relentless Rats", "Creature — Rat",
              "Relentless Rats gets +1/+1 for each other creature you control named Relentless Rats.\n"
              "A deck can have any number of cards named Relentless Rats.", ["B"]),
        _card("Seven Dwarves", "Creature — Dwarf",
              "A deck can have up to seven cards named Seven Dwarves.", ["R"]),
        _card("Kenrith, the Returned King", "Legendary Creature — Human Noble", "", ["W", "U", "B", "R", "G"]),
        _card("Ajani Goldmane", "Legendary Planeswalker — Ajani", "+1: You gain 2 life.", ["W"]),
        _card("Aminatou, the Fateshifter", "Legendary Planeswalker — Aminatou",
              "Aminatou, the Fateshifter can be your commander.", ["W", "U", "B"]),
        _card("Urabrask // The Great Work", "Legendary Creature — Phyrexian Praetor // Enchantment — Saga", "", ["R"]),
        _card("Sol Ring", "Artifact", "{T}: Add {C}{C}."),
        _card("Restricted Thing", "Artifact", "", [],
              {**_ALL_LEGAL, "legacy": "restricted"}),
    ]
}


class _StubRepository:
    fits_color_identity = staticmethod(CardRepository.fits_color_identity)

    def get_card(self, name: str) -> CardRecord | None:
        return CARDS.get(name)


validator = DeckValidator(_StubRepository())  # type: ignore[arg-type]


def _validate(fmt: str, main: dict[str, int], side: dict[str, int] | None = None,
              commander: str | None = None):
    return validator.validate(ValidateDeckRequest(
        format=fmt,
        mainboard=[CardRef(name=n, quantity=q) for n, q in main.items()],
        sideboard=[CardRef(name=n, quantity=q) for n, q in (side or {}).items()],
        commander=commander,
    ))


# ── rules.py ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("name", ["Mountain", "Snow-Covered Mountain", "Wastes"])
def test_every_basic_is_unlimited(name):
    assert is_basic_land(CARDS[name])
    assert copy_limit(CARDS[name], "modern") is None
    assert copy_limit(CARDS[name], "commander") is None


def test_any_number_cards_are_unlimited_even_in_commander():
    assert copy_limit(CARDS["Relentless Rats"], "modern") is None
    assert copy_limit(CARDS["Relentless Rats"], "commander") is None


def test_up_to_n_cards_cap_at_n():
    assert copy_limit(CARDS["Seven Dwarves"], "modern") == 7
    assert copy_limit(CARDS["Seven Dwarves"], "commander") == 7


def test_default_limits():
    assert copy_limit(CARDS["Lightning Bolt"], "modern") == 4
    assert copy_limit(CARDS["Lightning Bolt"], "commander") == 1
    assert copy_limit(CARDS["Restricted Thing"], "legacy") == 1


def test_commander_eligibility():
    assert can_be_commander(CARDS["Kenrith, the Returned King"])
    assert can_be_commander(CARDS["Aminatou, the Fateshifter"])  # "can be your commander"
    assert can_be_commander(CARDS["Urabrask // The Great Work"])  # front face decides
    assert not can_be_commander(CARDS["Ajani Goldmane"])  # legendary planeswalker without the text
    assert not can_be_commander(CARDS["Sol Ring"])


# ── validator: constructed ───────────────────────────────────────────────


def test_more_than_sixty_cards_is_legal():
    result = _validate("modern", {"Lightning Bolt": 4, "Mountain": 60})
    assert result.is_legal, result.errors


def test_fewer_than_sixty_cards_is_illegal():
    result = _validate("modern", {"Lightning Bolt": 4, "Mountain": 55})
    assert not result.is_legal
    assert any("at least 60" in e for e in result.errors)


def test_sideboard_over_fifteen_is_illegal():
    result = _validate("modern", {"Mountain": 60}, side={"Lightning Bolt": 4, "Snow-Covered Mountain": 12})
    assert not result.is_legal
    assert any("at most 15" in e for e in result.errors)


def test_short_sideboard_is_legal_with_a_warning():
    result = _validate("modern", {"Mountain": 60}, side={"Lightning Bolt": 4})
    assert result.is_legal, result.errors
    assert any("15-card sideboard" in w for w in result.warnings)


def test_snow_basics_are_not_capped():
    result = _validate("modern", {"Lightning Bolt": 4, "Snow-Covered Mountain": 56})
    assert result.is_legal, result.errors


def test_relentless_rats_are_not_capped():
    result = _validate("modern", {"Relentless Rats": 36, "Mountain": 24})
    assert result.is_legal, result.errors


def test_seven_dwarves_cap_at_seven():
    assert _validate("modern", {"Seven Dwarves": 7, "Mountain": 53}).is_legal
    result = _validate("modern", {"Seven Dwarves": 8, "Mountain": 52})
    assert any("7-copy limit" in e for e in result.errors)


def test_copies_are_counted_across_mainboard_and_sideboard():
    result = _validate("modern", {"Lightning Bolt": 4, "Mountain": 56}, side={"Lightning Bolt": 1})
    assert not result.is_legal
    assert any("Lightning Bolt exceeds the 4-copy limit" in e for e in result.errors)


def test_restricted_is_counted_in_total_not_per_entry():
    result = _validate("legacy", {"Restricted Thing": 1, "Mountain": 59}, side={"Restricted Thing": 1})
    assert not result.is_legal
    assert any("restricted" in e for e in result.errors)


# ── validator: commander ─────────────────────────────────────────────────


def test_commander_in_its_own_99_breaks_singleton():
    result = _validate("commander", {"Kenrith, the Returned King": 1, "Mountain": 98},
                       commander="Kenrith, the Returned King")
    assert not result.is_legal
    assert any("singleton" in e for e in result.errors)


def test_valid_commander_deck_is_legal():
    result = _validate("commander", {"Sol Ring": 1, "Mountain": 98}, commander="Kenrith, the Returned King")
    assert result.is_legal, result.errors


def test_non_commander_planeswalker_is_rejected():
    result = _validate("commander", {"Sol Ring": 1, "Mountain": 98}, commander="Ajani Goldmane")
    assert not result.is_legal
    assert any("can't be your commander" in e for e in result.errors)


def test_relentless_rats_allowed_in_commander():
    # Rats are black; Kenrith's identity covers it.
    result = _validate("commander", {"Relentless Rats": 30, "Mountain": 69}, commander="Kenrith, the Returned King")
    assert result.is_legal, result.errors


# ── Color-source warning (Notion: "color source warning fires when color
#    demand is unmet") ──────────────────────────────────────────────────

CARDS["Counterspell"] = _card("Counterspell", "Instant", "Counter target spell.", ["U"])
CARDS["Counterspell"].mana_cost = "{U}{U}"
CARDS["Island"] = _card("Island", "Basic Land — Island")
CARDS["Opt"] = _card("Opt", "Instant", "Scry 1. Draw a card.", ["U"])


def test_color_source_warning_names_the_unsupported_color():
    # Eight blue cards (the validator's demand unit), zero blue sources:
    # the warning must name blue and only blue.
    result = _validate("modern", {"Counterspell": 4, "Opt": 4, "Lightning Bolt": 4, "Mountain": 48})
    blue = [w for w in result.warnings if "U requirements" in w]
    assert blue, result.warnings
    assert "only 0 likely sources" in blue[0]
    assert not any("R requirements" in w for w in result.warnings)


def test_color_source_warning_is_quiet_when_sources_cover_demand():
    result = _validate("modern", {"Counterspell": 4, "Opt": 4, "Island": 26, "Mountain": 26})
    assert not any("requirements" in w for w in result.warnings), result.warnings
