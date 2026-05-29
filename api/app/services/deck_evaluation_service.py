"""Service that runs the deck-evaluation engine on a concrete decklist.

Resolves card names against the repository, profiles them (Phase-1
oracle parser), expands by quantity, and runs the multi-signal
:func:`evaluate_deck` battery. This is the API surface for the
"how good is this exact list?" question — distinct from the optimizer,
which *builds* a list.
"""

from __future__ import annotations

import logging

from app.oracle.ast_to_profile import build_card_profile
from app.oracle.profile import CardProfile
from app.services.card_repository import CardRepository
from app.sim.evaluation import evaluate_deck

logger = logging.getLogger(__name__)


def _record_dict(card) -> dict:
    return {
        "name": getattr(card, "name", ""),
        "mana_cost": getattr(card, "mana_cost", ""),
        "mana_value": getattr(card, "mana_value", 0),
        "type_line": getattr(card, "type_line", ""),
        "oracle_text": getattr(card, "oracle_text", ""),
        "keywords": getattr(card, "keywords", []),
        "tags": getattr(card, "tags", []),
        "color_identity": getattr(card, "color_identity", []),
        "colors": getattr(card, "colors", []),
    }


def evaluate_decklist(
    *,
    format_id: str,
    mainboard,
    repository: CardRepository,
    games: int = 200,
    seed: int = 1729,
) -> dict:
    """Build profiles for every card in ``mainboard`` and evaluate.

    ``mainboard`` is an iterable of objects with ``.name`` and
    ``.quantity`` (e.g. :class:`app.models.CardRef`). Unresolvable card
    names are reported in ``unresolved_cards`` rather than failing the
    whole request.
    """
    deck: list[tuple[CardProfile, str]] = []
    unresolved: list[str] = []
    for ref in mainboard:
        card = repository.get_card(ref.name)
        if card is None:
            unresolved.append(ref.name)
            continue
        record = _record_dict(card)
        profile = build_card_profile(record)
        type_line = record.get("type_line", "")
        deck.extend([(profile, type_line)] * int(ref.quantity))

    if not deck:
        raise ValueError(
            "no resolvable cards in decklist"
            + (f" (unresolved: {', '.join(unresolved)})" if unresolved else "")
        )

    # Commander games run a touch longer (40 life, slower clocks).
    max_turns = 14 if format_id == "commander" else 12
    evaluation = evaluate_deck(
        deck, format_id=format_id, games=games, max_turns=max_turns, seed=seed
    )
    result = evaluation.to_dict()
    result["cards_evaluated"] = len(deck)
    result["unresolved_cards"] = unresolved
    return result
