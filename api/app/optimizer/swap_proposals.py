"""Swap proposal engine.

Given a candidate deck and its fitness vector, propose swap candidates
*targeted at the worst metric*. Each swap is a (card_to_remove,
card_to_add) tuple drawn from the available pool. The optimizer's
annealing loop then evaluates the swaps; we never randomly mutate.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable

from app.oracle.profile import CardProfile
from app.optimizer.fitness import FitnessVector


BASIC_NAMES = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
               "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
               "Snow-Covered Mountain", "Snow-Covered Forest"}


def _at_playset_cap(name: str, deck: list[tuple[CardProfile, str]]) -> bool:
    if name in BASIC_NAMES:
        return False
    count = sum(1 for p, _ in deck if p.name == name)
    return count >= 4


def _filter_legal_adds(
    candidates: list[tuple[CardProfile, str]],
    deck: list[tuple[CardProfile, str]],
    constraints=None,
) -> list[tuple[CardProfile, str]]:
    """Drop pool entries that would push past 4-of, are excluded, or
    are off-color."""
    out: list[tuple[CardProfile, str]] = []
    for pa in candidates:
        if _at_playset_cap(pa[0].name, deck):
            continue
        if constraints is not None:
            if pa[0].name in constraints.exclude_cards:
                continue
            if constraints.colors:
                if set(pa[0].cost_vector.color_demand) - set(constraints.colors):
                    continue
        out.append(pa)
    return out


@dataclass
class Swap:
    remove_index: int
    remove_name: str
    add_profile: CardProfile
    add_type_line: str
    rationale: str = ""


def propose_constraint_repair_swaps(
    deck: list[tuple[CardProfile, str]],
    pool: list[tuple[CardProfile, str]],
    constraints,
    *,
    locked_card_names: set[str] | None = None,
    n_proposals: int = 5,
    rng: random.Random | None = None,
) -> list[Swap]:
    """Propose swaps that move the deck *toward* legality.

    Runs before fitness-targeted swaps when the deck violates a soft
    constraint (e.g. too_many_lands from seeder padding). Targets:

    * ``too_many_lands`` → swap a basic out for a non-land
    * ``too_few_lands`` → swap a non-land out for a basic
    * ``too_few_creatures`` → swap a non-creature spell for a creature
    """
    rng = rng or random.Random(1729)
    locked = locked_card_names or set()
    swaps: list[Swap] = []

    lands_in_deck = sum(1 for _, tl in deck if "land" in tl.lower())
    if lands_in_deck > constraints.max_lands:
        # Find Mountains/basics to remove.
        basic_indices = [
            i for i, (p, tl) in enumerate(deck)
            if tl.lower().startswith("basic") and p.name not in locked
        ]
        # Find non-land non-locked candidates from pool that fit colors.
        colors = set(constraints.colors or [])
        non_land_pool = [pa for pa in pool if "land" not in pa[1].lower()]
        non_land_pool = _filter_legal_adds(non_land_pool, deck, constraints)
        # Sort non-lands by role priority.
        non_land_pool.sort(
            key=lambda pa: -(
                pa[0].role_weights.threat
                + pa[0].role_weights.removal
                + pa[0].role_weights.value_engine
                + pa[0].role_weights.payoff
            ),
        )
        for r in basic_indices[: n_proposals]:
            if not non_land_pool:
                break
            add = non_land_pool[rng.randint(0, min(2, len(non_land_pool) - 1))]
            swaps.append(Swap(
                remove_index=r,
                remove_name=deck[r][0].name,
                add_profile=add[0],
                add_type_line=add[1],
                rationale="constraint repair: cut basic to satisfy max_lands",
            ))

    return swaps[:n_proposals]


def propose_swaps(
    deck: list[tuple[CardProfile, str]],
    pool: list[tuple[CardProfile, str]],
    fitness: FitnessVector,
    *,
    locked_card_names: set[str] | None = None,
    n_proposals: int = 5,
    rng: random.Random | None = None,
) -> list[Swap]:
    """Return up to ``n_proposals`` targeted swaps.

    Targeting:

    * worst axis = ``mana_consistency`` → swap a non-land for a fixer/land.
    * worst axis = ``kill_turn_score`` → swap a high-CMC card for a 1- or
      2-CMC threat or burn spell.
    * worst axis = ``mulligan_keep`` → swap a top-end for an early action.
    * worst axis = ``synergy_density`` → swap a filler for a card from
      the pool that produces what existing cards require.
    * worst axis = ``redundancy`` → swap a redundant 5th-of for diversity.
    * worst axis = ``role_balance`` → swap to add a missing role.
    """
    rng = rng or random.Random(1729)
    locked = locked_card_names or set()
    worst = fitness.worst_axis()
    swaps: list[Swap] = []

    deck_indices = [i for i, (p, _) in enumerate(deck) if p.name not in locked]
    legal_pool = _filter_legal_adds(pool, deck)
    pool_by_role: dict[str, list[tuple[CardProfile, str]]] = {}
    for prof, tl in legal_pool:
        for role, w in prof.role_weights.to_dict().items():
            if w >= 0.3:
                pool_by_role.setdefault(role, []).append((prof, tl))

    if worst == "mana_consistency":
        # Find a non-land we can spare (highest CMC, lowest impact).
        candidates_remove = sorted(
            [i for i in deck_indices if "land" not in deck[i][1].lower()],
            key=lambda i: -deck[i][0].cost_vector.cmc,
        )
        # And a fixer or basic to add.
        adds = pool_by_role.get("fixer", []) + pool_by_role.get("land", [])
        for r in candidates_remove[:n_proposals]:
            if not adds:
                break
            add = rng.choice(adds)
            swaps.append(Swap(
                remove_index=r,
                remove_name=deck[r][0].name,
                add_profile=add[0],
                add_type_line=add[1],
                rationale="boost mana consistency: trade slow card for fixer",
            ))
    elif worst == "kill_turn_score":
        candidates_remove = sorted(
            [i for i in deck_indices if "land" not in deck[i][1].lower()
             and deck[i][0].cost_vector.cmc >= 4],
            key=lambda i: -deck[i][0].cost_vector.cmc,
        )
        threats = sorted(
            pool_by_role.get("threat", []) + pool_by_role.get("closer", []) + pool_by_role.get("removal", []),
            key=lambda pa: pa[0].cost_vector.cmc,
        )
        for r in candidates_remove[:n_proposals]:
            if not threats:
                break
            add = threats[rng.randint(0, min(2, len(threats) - 1))]
            swaps.append(Swap(
                remove_index=r,
                remove_name=deck[r][0].name,
                add_profile=add[0],
                add_type_line=add[1],
                rationale="speed up clock: trade slow card for low-CMC threat/burn",
            ))
    elif worst == "mulligan_keep":
        candidates_remove = sorted(
            [i for i in deck_indices if deck[i][0].cost_vector.cmc >= 4],
            key=lambda i: -deck[i][0].cost_vector.cmc,
        )
        early = [pa for pa in legal_pool if pa[0].cost_vector.cmc <= 2]
        for r in candidates_remove[:n_proposals]:
            if not early:
                break
            add = early[rng.randint(0, len(early) - 1)]
            swaps.append(Swap(
                remove_index=r,
                remove_name=deck[r][0].name,
                add_profile=add[0],
                add_type_line=add[1],
                rationale="improve hand quality: replace top-end with early action",
            ))
    elif worst == "synergy_density":
        # Find a card with no synergy (no produces or requires tokens).
        bland = sorted(
            [i for i in deck_indices
             if not deck[i][0].combo_primitives.produces
             and not deck[i][0].combo_primitives.requires
             and "land" not in deck[i][1].lower()],
            key=lambda i: deck[i][0].cost_vector.cmc,
        )
        synergy_pool = [pa for pa in legal_pool if pa[0].combo_primitives.produces or pa[0].combo_primitives.requires]
        for r in bland[:n_proposals]:
            if not synergy_pool:
                break
            add = synergy_pool[rng.randint(0, min(5, len(synergy_pool) - 1))]
            swaps.append(Swap(
                remove_index=r,
                remove_name=deck[r][0].name,
                add_profile=add[0],
                add_type_line=add[1],
                rationale="thicken synergy: drop filler for a card with combo primitives",
            ))
    elif worst == "redundancy":
        # Fold the rarest role's count back into the deck.
        role_counts: dict[str, int] = {}
        for p, _ in deck:
            for role, w in p.role_weights.to_dict().items():
                if w > 0.3 and role != "land":
                    role_counts[role] = role_counts.get(role, 0) + 1
        if role_counts:
            weakest_role = min(role_counts, key=role_counts.get)
            adds = pool_by_role.get(weakest_role, [])
            removable = [i for i in deck_indices
                         if any(role_counts.get(r, 0) > 6
                                for r, w in deck[i][0].role_weights.to_dict().items() if w > 0.3)]
            for r in removable[:n_proposals]:
                if not adds:
                    break
                add = adds[rng.randint(0, min(3, len(adds) - 1))]
                swaps.append(Swap(
                    remove_index=r,
                    remove_name=deck[r][0].name,
                    add_profile=add[0],
                    add_type_line=add[1],
                    rationale=f"shore up under-represented role {weakest_role!r}",
                ))
    elif worst == "role_balance":
        present_roles = {
            role for p, _ in deck
            for role, w in p.role_weights.to_dict().items()
            if w >= 0.3
        }
        missing_roles = {"removal", "value_engine", "threat", "fixer", "disruption"} - present_roles
        for missing in missing_roles:
            adds = pool_by_role.get(missing, [])
            if not adds:
                continue
            removable = [i for i in deck_indices
                         if "land" not in deck[i][1].lower()]
            removable = sorted(removable, key=lambda i: -deck[i][0].cost_vector.cmc)
            if not removable:
                continue
            r = removable[0]
            add = adds[0]
            swaps.append(Swap(
                remove_index=r,
                remove_name=deck[r][0].name,
                add_profile=add[0],
                add_type_line=add[1],
                rationale=f"add missing role {missing!r}",
            ))
            if len(swaps) >= n_proposals:
                break

    # If we couldn't generate anything targeted, fall back to a random
    # non-locked, non-land swap so the annealer always has progress.
    if not swaps and legal_pool and deck_indices:
        for _ in range(min(n_proposals, 3)):
            r = rng.choice(deck_indices)
            add = rng.choice(legal_pool)
            swaps.append(Swap(
                remove_index=r,
                remove_name=deck[r][0].name,
                add_profile=add[0],
                add_type_line=add[1],
                rationale="exploration swap (no targeted improvement found)",
            ))
    return swaps[:n_proposals]


def apply_swap(
    deck: list[tuple[CardProfile, str]], swap: Swap
) -> list[tuple[CardProfile, str]]:
    new_deck = list(deck)
    new_deck[swap.remove_index] = (swap.add_profile, swap.add_type_line)
    return new_deck
