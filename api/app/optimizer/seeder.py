"""Seeder: produce a small set of candidate decks to anneal from.

For Modern, the seeder pulls top archetypes matching the constraints
(via the existing :mod:`card_repository.top_archetypes`) and constructs
a candidate deck following the archetype's package recipe. Three
diverse seeds is the sweet spot — enough variation to escape local
maxima, not so many that the worker queue chokes.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.oracle.profile import CardProfile
from app.optimizer.constraints import OptimizerConstraints


@dataclass
class Seed:
    deck: list[tuple[CardProfile, str]]
    label: str
    archetype_id: str | None = None


def seed_candidates(
    constraints: OptimizerConstraints,
    pool: list[tuple[CardProfile, str]],
    *,
    archetype_recipes: list[dict] | None = None,
    n_seeds: int = 3,
) -> list[Seed]:
    """Build seed decks from archetype recipes or a pure pool fallback.

    Each ``archetype_recipes`` entry is::

        {"id": "modern_burn",
         "label": "Modern Burn",
         "card_quotas": {"Lightning Bolt": 4, "Goblin Guide": 4, ...}}

    If recipes are absent or insufficient, the seeder falls back to
    filling the deck role-by-role from the available pool.
    """
    seeds: list[Seed] = []
    pool_by_name = {p.name: (p, tl) for p, tl in pool}
    deck_size = constraints.deck_size

    recipes = archetype_recipes or []
    for recipe in recipes[:n_seeds]:
        deck: list[tuple[CardProfile, str]] = []
        for must in constraints.include_cards:
            if must in pool_by_name:
                deck.append(pool_by_name[must])
        for name, quota in (recipe.get("card_quotas") or {}).items():
            if name in constraints.exclude_cards:
                continue
            if name not in pool_by_name:
                continue
            for _ in range(int(quota)):
                if len(deck) >= deck_size:
                    break
                deck.append(pool_by_name[name])
        # Fill remaining slots from pool by role priority.
        deck = _fill_to_size(deck, pool, constraints)
        seeds.append(Seed(deck=deck, label=recipe.get("label", recipe.get("id", "seed")),
                          archetype_id=recipe.get("id")))

    while len(seeds) < n_seeds:
        deck = []
        for must in constraints.include_cards:
            if must in pool_by_name:
                deck.append(pool_by_name[must])
        deck = _fill_to_size(deck, pool, constraints)
        seeds.append(Seed(deck=deck, label=f"pool-fallback-{len(seeds)}"))

    return seeds


def _fill_to_size(
    deck: list[tuple[CardProfile, str]],
    pool: list[tuple[CardProfile, str]],
    constraints: OptimizerConstraints,
) -> list[tuple[CardProfile, str]]:
    """Greedily fill ``deck`` to ``constraints.deck_size`` from ``pool``.

    Adds lands first to hit ``min_lands``, then non-lands sorted by
    role weight (threat → removal → value_engine → others).
    """
    excluded = set(constraints.exclude_cards)
    deck = [pa for pa in deck if pa[0].name not in excluded]
    target_size = constraints.deck_size

    counts: dict[str, int] = {}
    for p, _ in deck:
        counts[p.name] = counts.get(p.name, 0) + 1

    cap = 1 if constraints.singleton else 4

    def can_add(name: str) -> bool:
        return counts.get(name, 0) < cap or name in {"Mountain", "Island", "Swamp", "Plains", "Forest", "Wastes"}

    # Land target.
    target_lands = max(constraints.min_lands, 20)
    current_lands = sum(1 for _, tl in deck if "land" in tl.lower())
    pool_lands = [pa for pa in pool if "land" in pa[1].lower() and pa[0].name not in excluded]
    pool_lands.sort(key=lambda pa: -_color_match(pa[0], constraints.colors))
    for pa in pool_lands:
        if len(deck) >= target_size or current_lands >= target_lands:
            break
        if pa[0].name in excluded:
            continue
        if not can_add(pa[0].name):
            continue
        deck.append(pa)
        counts[pa[0].name] = counts.get(pa[0].name, 0) + 1
        current_lands += 1

    # Non-land slots.
    pool_nonland = [pa for pa in pool if "land" not in pa[1].lower() and pa[0].name not in excluded]
    pool_nonland.sort(key=lambda pa: -_card_priority(pa[0]))
    for pa in pool_nonland:
        if len(deck) >= target_size:
            break
        if not can_add(pa[0].name):
            continue
        # Color identity check.
        if constraints.colors:
            offcolor = set(pa[0].cost_vector.color_demand.keys()) - set(constraints.colors)
            if offcolor:
                continue
        deck.append(pa)
        counts[pa[0].name] = counts.get(pa[0].name, 0) + 1

    # Pad to target_size. Non-lands respect the playset cap; basics may
    # repeat. We never under-fill — under-sized seeds are unrecoverable.
    while len(deck) < target_size:
        added_this_pass = False
        for pa in pool_nonland:
            if len(deck) >= target_size:
                break
            if counts.get(pa[0].name, 0) >= cap:
                continue
            if constraints.colors and (set(pa[0].cost_vector.color_demand) - set(constraints.colors)):
                continue
            deck.append(pa)
            counts[pa[0].name] = counts.get(pa[0].name, 0) + 1
            added_this_pass = True
        if len(deck) >= target_size:
            break
        for pa in pool_lands:
            if len(deck) >= target_size:
                break
            if pa[1].lower().startswith("basic"):
                deck.append(pa)
                counts[pa[0].name] = counts.get(pa[0].name, 0) + 1
                current_lands += 1
                added_this_pass = True
        if not added_this_pass:
            break
    return deck[:target_size]


def _color_match(profile: CardProfile, colors: list[str]) -> int:
    if not colors:
        return 0
    return sum(1 for c in profile.cost_vector.color_demand if c in colors)


def _card_priority(profile: CardProfile) -> float:
    rw = profile.role_weights.to_dict()
    return (
        rw.get("threat", 0) * 3
        + rw.get("removal", 0) * 3
        + rw.get("value_engine", 0) * 2
        + rw.get("payoff", 0) * 2
        + rw.get("disruption", 0) * 2
        + rw.get("closer", 0) * 1.5
        + rw.get("fixer", 0) * 1
    )
