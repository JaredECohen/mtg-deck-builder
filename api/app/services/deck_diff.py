"""Deck diff — compare two decklists card-by-card.

Pure, dependency-free. Powers the "what changed?" UX between an original
list and a refined/optimized one, and the history view's version compare.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _counts(mainboard) -> dict[str, int]:
    out: dict[str, int] = {}
    for ref in mainboard:
        name = ref["name"] if isinstance(ref, dict) else ref.name
        qty = ref["quantity"] if isinstance(ref, dict) else ref.quantity
        out[name] = out.get(name, 0) + int(qty)
    return out


@dataclass
class DeckDiff:
    added: list[dict] = field(default_factory=list)      # in B, not A
    removed: list[dict] = field(default_factory=list)    # in A, not B
    increased: list[dict] = field(default_factory=list)  # qty up A→B
    decreased: list[dict] = field(default_factory=list)  # qty down A→B
    unchanged: list[dict] = field(default_factory=list)

    @property
    def cards_added(self) -> int:
        return sum(e["quantity"] for e in self.added) + sum(e["delta"] for e in self.increased)

    @property
    def cards_removed(self) -> int:
        return sum(e["quantity"] for e in self.removed) + sum(e["delta"] for e in self.decreased)

    @property
    def total_changes(self) -> int:
        return self.cards_added + self.cards_removed

    def to_dict(self) -> dict:
        return {
            "added": self.added,
            "removed": self.removed,
            "increased": self.increased,
            "decreased": self.decreased,
            "unchanged": self.unchanged,
            "summary": {
                "cards_added": self.cards_added,
                "cards_removed": self.cards_removed,
                "total_changes": self.total_changes,
                "identical": self.total_changes == 0,
            },
        }


def diff_decks(mainboard_a, mainboard_b) -> DeckDiff:
    """Diff ``mainboard_a`` (before) against ``mainboard_b`` (after).

    Each input is an iterable of CardRef-likes (``.name``/``.quantity``
    or dict with those keys). Returns a structured, JSON-serializable
    diff sorted by card name for stable output.
    """
    ca, cb = _counts(mainboard_a), _counts(mainboard_b)
    diff = DeckDiff()
    for name in sorted(set(ca) | set(cb)):
        a, b = ca.get(name, 0), cb.get(name, 0)
        if a == 0 and b > 0:
            diff.added.append({"name": name, "quantity": b})
        elif b == 0 and a > 0:
            diff.removed.append({"name": name, "quantity": a})
        elif b > a:
            diff.increased.append({"name": name, "from": a, "to": b, "delta": b - a})
        elif b < a:
            diff.decreased.append({"name": name, "from": a, "to": b, "delta": a - b})
        else:
            diff.unchanged.append({"name": name, "quantity": a})
    return diff
