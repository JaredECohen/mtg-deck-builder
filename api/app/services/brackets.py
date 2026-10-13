"""Commander Brackets (WotC, 2025): assess a list and constrain a build.

Brackets are 1 Exhibition, 2 Core, 3 Upgraded, 4 Optimized, 5 cEDH. The
published guidance this module encodes:

- Brackets 1-2: no Game Changers, no mass land denial, no chained extra
  turns, no two-card infinite combos; tutors sparse.
- Bracket 3: up to three Game Changers; no mass land denial; no chained
  extra turns; no early-game two-card combos.
- Bracket 4: no restrictions beyond the banned list. Bracket 5 is the same
  card pool played at a competitive table, so it can't be read off a list.

The estimate is therefore a floor read from the list (2, 3 or 4); 1 and 5 are
about intent and table expectations, which the notes say.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Protocol

from app.config import DATA_DIR
from app.models import BracketAssessment, CardRecord

_EXTRA_TURN = re.compile(r"take an extra turn", re.IGNORECASE)
_TUTOR = re.compile(r"search your library for (?:a|an|any|up to \w+) (?:[\w\- ]+ )?cards?\b", re.IGNORECASE)
_LAND_TUTOR = re.compile(r"search your library for (?:a|an|up to \w+) (?:basic )?(?:land|forest|plains|island|swamp|mountain)", re.IGNORECASE)
_MLD_TEXT = re.compile(
    r"destroy all lands|each player sacrifices (?:all|\w+) lands|destroy all nonbasic lands"
    r"|lands don't untap",
    re.IGNORECASE,
)


class _Lookup(Protocol):
    def get_card(self, name: str) -> CardRecord | None: ...


@lru_cache(maxsize=1)
def bracket_data() -> dict:
    data = json.loads((DATA_DIR / "game_changers.json").read_text(encoding="utf-8"))
    combos = [list(pair) for pair in data.get("commander_two_card_combos", [])]
    registry = DATA_DIR.parent / "synergy" / "combos.json"
    if registry.exists():
        for combo in json.loads(registry.read_text(encoding="utf-8")).get("combos", []):
            if len(combo.get("cards", [])) == 2:
                combos.append(list(combo["cards"]))
    return {
        "as_of": data.get("as_of"),
        "game_changers": frozenset(data["game_changers"]),
        "mass_land_denial": frozenset(data["mass_land_denial"]),
        "two_card_combos": [tuple(pair) for pair in combos],
    }


def _text(card: CardRecord) -> str:
    return card.oracle_text or " ".join(face.oracle_text or "" for face in card.faces)


def is_mass_land_denial(card: CardRecord) -> bool:
    return card.name in bracket_data()["mass_land_denial"] or bool(_MLD_TEXT.search(_text(card)))


def is_extra_turn(card: CardRecord) -> bool:
    return bool(_EXTRA_TURN.search(_text(card)))


def is_tutor(card: CardRecord) -> bool:
    text = _text(card)
    return bool(_TUTOR.search(text)) and not _LAND_TUTOR.search(text)


def assess(names: list[str], repository: _Lookup, target: int | None = None) -> BracketAssessment:
    """Bracket floor for a list (commander included in ``names``)."""
    data = bracket_data()
    cards = [card for name in dict.fromkeys(names) if (card := repository.get_card(name)) is not None]
    present = {card.name for card in cards}
    game_changers = sorted(card.name for card in cards if card.name in data["game_changers"])
    mld = sorted(card.name for card in cards if is_mass_land_denial(card))
    extra_turns = sorted(card.name for card in cards if is_extra_turn(card))
    tutors = sorted(card.name for card in cards if is_tutor(card))
    combos = [list(pair) for pair in data["two_card_combos"] if set(pair) <= present]

    estimated = 2
    notes: list[str] = []
    if game_changers:
        estimated = 3
        notes.append(f"{len(game_changers)} Game Changer(s): bracket 3 allows up to three.")
    if len(game_changers) > 3:
        estimated = 4
        notes.append("More than three Game Changers puts the list in bracket 4.")
    if mld:
        estimated = 4
        notes.append("Mass land denial is bracket 4+.")
    if len(extra_turns) >= 2:
        estimated = max(estimated, 4)
        notes.append("Multiple extra-turn cards can chain turns, which is bracket 4+.")
    if combos:
        estimated = max(estimated, 4)
        notes.append("A two-card combo is in the list; brackets 1-3 avoid them (bracket 3 only late-game).")
    if len(tutors) > 3 and estimated < 3:
        estimated = 3
        notes.append(f"{len(tutors)} tutors: brackets 1-2 keep tutors sparse.")
    notes.append(
        "Bracket 1 (Exhibition) and 5 (cEDH) depend on theme and table intent, so the list can only "
        "show a floor of 2-4."
    )
    return BracketAssessment(
        estimated=estimated,
        target=target,
        game_changers=game_changers,
        mass_land_denial=mld,
        extra_turns=extra_turns,
        tutors=tutors,
        two_card_combos=combos,
        notes=notes,
        game_changers_as_of=data["as_of"],
    )


def excluded_for_bracket(
    target: int | None,
    allow: set[str],
    mld_names: frozenset[str],
    extra_turn_names: frozenset[str],
) -> set[str]:
    """Lower-cased names a build at ``target`` must not add on its own.

    ``allow`` are cards the user explicitly asked for; at bracket 3 they may
    keep up to three Game Changers (and their own extra-turn cards).
    ``mld_names`` / ``extra_turn_names`` are the pool's precomputed matches.
    """
    if target is None or target >= 4:
        return set()
    data = bracket_data()
    allowed_gc = set(sorted(name for name in allow if name in data["game_changers"])[:3]) if target == 3 else set()
    banned = {name.lower() for name in data["game_changers"] if name not in allowed_gc}
    banned |= {name.lower() for name in mld_names}
    banned |= {name.lower() for name in extra_turn_names if name not in allow}
    return banned


def combo_pieces_to_cut(names: set[str], target: int | None, keep: set[str]) -> set[str]:
    """For brackets 1-2: one piece of each two-card combo present (never a
    card in ``keep``)."""
    if target is None or target >= 3:
        return set()
    cut: set[str] = set()
    for a, b in bracket_data()["two_card_combos"]:
        if a in names and b in names and not ({a, b} & cut):
            victim = b if b not in keep else a
            if victim not in keep:
                cut.add(victim)
    return cut
