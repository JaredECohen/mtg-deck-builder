"""Keep generated prose about the deck that was actually built (spec §26).

LLM-written summaries (compose / blend curation) and curated archetype blurbs
can name cards that never made the final list — the LLM invents them, or color
identity, budget or bracket filtering drops them later. A Talrand deck's
summary once said "Mizzix of the Izmagnus leads the deck" and "finish with
Grapeshot", none of which were in the 99. This module drops every sentence
that names a real card that isn't in the deck.
"""

from __future__ import annotations

import re
from typing import Protocol

from app.models import CardRecord

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_TOKEN = re.compile(r"[A-Za-zÀ-ÿ0-9'’\-,]+")
_MAX_NAME_WORDS = 7
# Card names that are also ordinary English in deck prose.
_COMMON_WORDS = frozenset({
    "opt", "island", "plains", "swamp", "mountain", "forest", "wastes", "duress", "shock", "fling",
    "counterspell", "negate", "disenchant", "regrowth", "mulligan", "storm", "lifelink", "flash",
    "ponder", "preordain", "brainstorm", "remand", "thoughtseize", "consider", "tribute",
})


class _Lookup(Protocol):
    def get_card(self, name: str) -> CardRecord | None: ...


def card_mentions(sentence: str, repository: _Lookup) -> set[str]:
    """Canonical names of real cards mentioned in ``sentence``.

    Spans of 1-7 tokens starting with a capitalized token are looked up; the
    longest match wins. Single-word matches are ignored at the start of a
    sentence or when they are everyday words, to avoid "Island count…" or
    "Storm off" false positives.
    """
    matches = list(_TOKEN.finditer(sentence))
    tokens = [m.group(0).strip(",") for m in matches]
    found: set[str] = set()
    i = 0
    while i < len(tokens):
        if not tokens[i][:1].isupper():
            i += 1
            continue
        matched = 0
        for length in range(min(_MAX_NAME_WORDS, len(tokens) - i), 0, -1):
            # Cut the span from the original text so internal punctuation
            # ("Atraxa, Praetors' Voice") survives.
            span = sentence[matches[i].start():matches[i + length - 1].end()].strip(" ,")
            if length == 1 and (i == 0 or span.lower() in _COMMON_WORDS):
                continue
            card = repository.get_card(span)
            if card is not None:
                found.add(card.name)
                matched = length
                break
        i += matched or 1
    return found


def ground_text(text: str, allowed: set[str], repository: _Lookup) -> tuple[str, list[str]]:
    """Drop sentences naming cards outside ``allowed``.

    Returns the kept text and the removed sentences. Face names of an allowed
    double-faced card count as allowed.
    """
    allowed_all = set(allowed)
    for name in allowed:
        allowed_all.update(part for part in name.split(" // "))
    kept: list[str] = []
    removed: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(text.strip()):
        if not sentence:
            continue
        mentions = card_mentions(sentence, repository)
        if any(m not in allowed_all and not set(m.split(" // ")) & allowed_all for m in mentions):
            removed.append(sentence)
        else:
            kept.append(sentence)
    return " ".join(kept), removed
