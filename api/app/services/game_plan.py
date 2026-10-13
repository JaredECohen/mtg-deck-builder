"""How to play the deck that was built (spec §11G), without an LLM.

Everything here is derived from the list itself, so it can't describe cards
that aren't in it:

- win conditions: the threats/payoffs the deck runs most of and that hit hardest;
- opening hand: land odds in seven cards from the exact land count
  (hypergeometric), with a keep range by deck speed;
- mulligan rules by speed (aggro / midrange / control / combo / commander);
- sideboard guide: every sideboard card's job, what it comes in against, and
  which main-deck cards it replaces;
- matchups: the format's corpus archetypes and what this list brings for them
  (no win-rate claims; the outlook is only set when the sideboard answers that
  opponent's plan);
- Commander: ramp / draw / removal / wipes / tutors / win-con packages.
"""

from __future__ import annotations

import re
from math import comb
from typing import Protocol

from app.models import (
    ArchetypeRecord,
    CardRecord,
    CardRef,
    GamePlan,
    MatchupNote,
    SideboardGuideEntry,
)
from app.rules import is_land_card
from app.services.sideboard_classes import classify

# Mana rocks/dorks ("{T}: Add") and land ramp that puts lands onto the battlefield.
_RAMP = re.compile(
    r"\{T\}(?:, [^:]+)?: Add \{"
    r"|search your library for (?:a|an|up to \w+) (?:basic )?(?:land|forest|plains|island|swamp|mountain)[^.]*onto the battlefield",
    re.IGNORECASE,
)
_DRAW = re.compile(r"draw (?:a|two|three|\w+) cards?", re.IGNORECASE)
_TUTOR = re.compile(r"search your library for (?:a|an) card", re.IGNORECASE)

# Opponent tags (corpus archetype tags) → the sideboard class that answers them.
_ANSWERS_FOR_TAG = {
    "graveyard": "graveyard_hate",
    "reanimator": "graveyard_hate",
    "artifact": "artifact_enchantment_removal",
    "artifacts": "artifact_enchantment_removal",
    "enchantments": "artifact_enchantment_removal",
    "combo": "counterspell",
    "control": "hand_disruption",
    "tokens": "sweeper",
    "go-wide": "sweeper",
    "burn": "lifegain",
    "aggro": "creature_removal",
    "pressure": "creature_removal",
}


class _Lookup(Protocol):
    def get_card(self, name: str) -> CardRecord | None: ...


def _speed(tags: list[str], avg_mv: float, land_count: int, deck_size: int) -> str:
    tagset = set(tags)
    if "combo" in tagset:
        return "combo"
    if tagset & {"aggro", "pressure", "burn"} or (avg_mv <= 2.0 and land_count <= deck_size * 0.35):
        return "aggro"
    if tagset & {"control"} or avg_mv >= 3.2:
        return "control"
    return "midrange"


def _p_lands_between(deck_size: int, lands: int, low: int, high: int, draws: int = 7) -> float:
    total = comb(deck_size, draws)
    return sum(
        comb(lands, k) * comb(deck_size - lands, draws - k)
        for k in range(low, high + 1)
        if 0 <= k <= lands and draws - k <= deck_size - lands
    ) / total


def build_game_plan(
    *,
    format_name: str,
    mainboard: list[CardRef],
    sideboard: list[CardRef],
    commander: str | None,
    tags: list[str],
    archetypes: list[ArchetypeRecord],
    repository: _Lookup,
) -> GamePlan:
    cards = [(ref, card) for ref in mainboard if (card := repository.get_card(ref.name)) is not None]
    deck_size = sum(ref.quantity for ref, _ in cards) or 1
    land_count = sum(ref.quantity for ref, card in cards if is_land_card(card))
    spells = [(ref, card) for ref, card in cards if not is_land_card(card)]
    spell_count = sum(ref.quantity for ref, _ in spells) or 1
    avg_mv = sum(card.mana_value * ref.quantity for ref, card in spells) / spell_count
    speed = "commander" if format_name == "commander" else _speed(tags, avg_mv, land_count, deck_size)

    # Win conditions: payoff/finisher/threat cards, weighted by copies and impact.
    def threat_score(ref: CardRef, card: CardRecord) -> float:
        tagset = set(card.tags)
        score = ref.quantity * 2 + card.mana_value
        if tagset & {"finisher", "payoff"}:
            score += 6
        if "Creature" in card.type_line or "Planeswalker" in card.type_line:
            score += 3
        return score

    threats = [
        (threat_score(ref, card), card.name) for ref, card in spells
        if set(card.tags) & {"finisher", "payoff", "pressure", "creature"}
        or "Creature" in card.type_line or "Planeswalker" in card.type_line
    ]
    win_conditions = ([commander] if commander else []) + [
        name for _, name in sorted(threats, reverse=True) if name != commander
    ][:3]

    # Opening hand odds.
    keep_low, keep_high = {
        "aggro": (1, 3), "midrange": (2, 4), "control": (3, 5), "combo": (2, 4), "commander": (3, 5),
    }[speed]
    p_keep = _p_lands_between(deck_size, land_count, keep_low, keep_high)
    p_screw = _p_lands_between(deck_size, land_count, 0, keep_low - 1)
    p_flood = _p_lands_between(deck_size, land_count, keep_high + 1, 7)
    opening_hand = [
        f"{land_count} lands in {deck_size} cards: a 7-card hand has {keep_low}-{keep_high} lands "
        f"{p_keep:.0%} of the time ({p_screw:.0%} too few, {p_flood:.0%} too many).",
    ]
    cheap = sum(ref.quantity for ref, card in spells if card.mana_value <= 2)
    opening_hand.append(
        f"{cheap} of {spell_count} spells cost 2 or less, so most hands can act by turn 2."
        if cheap >= spell_count * 0.5
        else f"Only {cheap} of {spell_count} spells cost 2 or less: keep hands that can cast something early."
    )

    mulligan = {
        "aggro": [
            "Keep 1-3 land hands with at least two plays costing 1-2.",
            "Mulligan 0- and 5+-land hands; a slow seven is worse than a fast six.",
        ],
        "midrange": [
            "Keep 2-4 lands with an early play and one piece of interaction.",
            "Mulligan hands that can't cast anything before turn 3.",
        ],
        "control": [
            "Keep 3-5 lands with interaction for the first turns; card quality catches up later.",
            "Mulligan two-landers without card draw — missing land drops loses to everything.",
        ],
        "combo": [
            "Keep hands with the engine piece or a way to find it, and enough mana to start on time.",
            "Mulligan aggressively into the combo; a fair hand rarely wins for this deck.",
        ],
        "commander": [
            "Keep 3-5 lands plus a ramp piece; your commander is always available.",
            "Many tables play a free first mulligan — use it on 0-2 land hands.",
        ],
    }[speed]

    # Sideboard guide.
    # Swap-out candidates: the most expensive non-playset spells; a list of
    # all playsets (Burn) falls back to its most expensive spells.
    main_by_mv = sorted(
        ((card.mana_value, card.name) for ref, card in spells if ref.quantity < 4 and card.name != commander),
        reverse=True,
    ) or sorted(((card.mana_value, card.name) for _, card in spells if card.name != commander), reverse=True)
    guide: list[SideboardGuideEntry] = []
    take_cursor = 0
    for ref in sideboard:
        card = repository.get_card(ref.name)
        if card is None:
            continue
        cls = classify(card)
        take_out = []
        if main_by_mv:
            take_out = [main_by_mv[take_cursor % len(main_by_mv)][1]]
            take_cursor += 1
        guide.append(SideboardGuideEntry(
            card=card.name,
            quantity=ref.quantity,
            purpose=cls.purpose if cls else "Flexible answer",
            bring_in_against=list(cls.against) if cls else ["matchups where it answers their key cards"],
            take_out=take_out,
        ))

    # Matchups against the format's corpus archetypes.
    side_classes = {cls.key for entry in sideboard if (c := repository.get_card(entry.name)) and (cls := classify(c))}
    main_classes = {cls.key for _, c in spells if (cls := classify(c))}
    matchups: list[MatchupNote] = []
    for archetype in sorted(archetypes, key=lambda a: a.source_count, reverse=True)[:5]:
        opp_tags = [tag.lower() for tag in archetype.tags]
        answers = [_ANSWERS_FOR_TAG[tag] for tag in opp_tags if tag in _ANSWERS_FOR_TAG]
        covered = [key for key in answers if key in side_classes or key in main_classes]
        plan = ", ".join(archetype.tags[:3]) or "its own plan"
        if covered:
            note = f"Plays {plan}. You have answers for it ({', '.join(sorted(set(k.replace('_', ' ') for k in covered)))})."
            outlook = "even"
        elif answers:
            note = f"Plays {plan}. Nothing in this list targets that plan; consider {answers[0].replace('_', ' ')}."
            outlook = "unknown"
        else:
            note = f"Plays {plan}."
            outlook = "unknown"
        matchups.append(MatchupNote(opponent=archetype.name, outlook=outlook, note=note))

    packages: dict[str, list[str]] = {}
    if format_name == "commander":
        def pick(predicate) -> list[str]:
            return sorted(card.name for _, card in spells if predicate(card))[:12]

        packages = {
            # Oracle text only: the stored "ramp" tag is noisy (Eldrazi Scion
            # makers, artifact removal).
            "ramp": pick(lambda c: bool(_RAMP.search(c.oracle_text or ""))),
            "draw": pick(lambda c: "draw" in c.tags or bool(_DRAW.search(c.oracle_text or ""))),
            "removal": pick(lambda c: (cls := classify(c)) is not None and cls.key in {"creature_removal", "artifact_enchantment_removal"}),
            "wipes": pick(lambda c: (cls := classify(c)) is not None and cls.key == "sweeper"),
            "tutors": pick(lambda c: bool(_TUTOR.search(c.oracle_text or ""))),
            "win_conditions": win_conditions[:4],
        }
        packages = {key: names for key, names in packages.items() if names}

    speed_text = {
        "aggro": "an aggressive deck: deploy cheap threats early and close before the opponent stabilizes",
        "midrange": "a midrange deck: trade resources early and win with stronger cards in the mid-game",
        "control": "a control deck: answer threats, out-draw the opponent, then close with a few finishers",
        "combo": "a combo deck: assemble the engine quickly while protecting it",
        "commander": "a Commander deck: develop mana, keep card flow going, and use the commander as the engine",
    }[speed]
    summary = f"This is {speed_text}."
    if win_conditions:
        summary += f" Main ways to win: {', '.join(win_conditions)}."
    return GamePlan(
        summary=summary,
        win_conditions=win_conditions,
        opening_hand=opening_hand,
        mulligan=mulligan,
        sideboard_guide=guide,
        matchups=matchups,
        commander_packages=packages,
    )
