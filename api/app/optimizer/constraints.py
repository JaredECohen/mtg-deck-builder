"""Hard-constraint filter for the optimizer.

User constraints are *hard*: a swap that violates them is rejected
before fitness is even computed. This is what stops budget creep,
off-color cards, and dropped includes during refinement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from app.optimizer.format_config import FORMATS, FormatConfig, get_format_config
from app.oracle.profile import CardProfile


@dataclass
class OptimizerConstraints:
    format: str = "modern"
    colors: list[str] = field(default_factory=list)
    deck_size: int | None = None  # None = read from format config
    sideboard_size: int | None = None
    budget_usd: float | None = None
    per_card_cap_usd: float | None = None
    include_cards: list[str] = field(default_factory=list)
    exclude_cards: list[str] = field(default_factory=list)
    min_lands: int | None = None
    max_lands: int | None = None
    min_creatures: int = 0
    commander_name: str | None = None
    singleton: bool | None = None  # None = read from format config

    def __post_init__(self) -> None:
        cfg = self.format_config
        if self.deck_size is None:
            self.deck_size = cfg.deck_size
        if self.sideboard_size is None:
            self.sideboard_size = cfg.sideboard_size
        if self.min_lands is None:
            self.min_lands = cfg.min_lands
        if self.max_lands is None:
            self.max_lands = cfg.max_lands
        if self.singleton is None:
            self.singleton = cfg.singleton

    @property
    def format_config(self) -> FormatConfig:
        return get_format_config(self.format)


@dataclass
class ConstraintViolation:
    code: str
    detail: str


def validate_constraints(
    deck: list[tuple[CardProfile, str]],
    constraints: OptimizerConstraints,
    *,
    card_prices: dict[str, float] | None = None,
) -> list[ConstraintViolation]:
    """Return any constraint violations for ``deck``. Empty = legal."""
    prices = card_prices or {}
    out: list[ConstraintViolation] = []

    if len(deck) != constraints.deck_size:
        out.append(ConstraintViolation(
            code="size",
            detail=f"deck has {len(deck)} cards, expected {constraints.deck_size}",
        ))

    names = [p.name for p, _ in deck]
    name_set = set(names)
    for must in constraints.include_cards:
        if must not in name_set:
            out.append(ConstraintViolation(
                code="missing_include", detail=f"required card {must!r} not in deck"
            ))
    for forbidden in constraints.exclude_cards:
        if forbidden in name_set:
            out.append(ConstraintViolation(
                code="excluded_present", detail=f"forbidden card {forbidden!r} in deck"
            ))

    if constraints.colors:
        deck_colors = set()
        for profile, _ in deck:
            for color in profile.cost_vector.color_demand:
                deck_colors.add(color)
        offcolor = deck_colors - set(constraints.colors)
        if offcolor:
            out.append(ConstraintViolation(
                code="off_color",
                detail=f"deck uses off-color pips: {sorted(offcolor)}",
            ))

    if constraints.budget_usd is not None:
        total = sum(prices.get(p.name, 0.0) for p, _ in deck)
        if total > constraints.budget_usd + 0.01:
            out.append(ConstraintViolation(
                code="over_budget",
                detail=f"total ${total:.2f} > budget ${constraints.budget_usd:.2f}",
            ))
    if constraints.per_card_cap_usd is not None:
        for profile, _ in deck:
            price = prices.get(profile.name, 0.0)
            if price > constraints.per_card_cap_usd:
                out.append(ConstraintViolation(
                    code="over_cap",
                    detail=f"{profile.name} ${price:.2f} > cap ${constraints.per_card_cap_usd:.2f}",
                ))

    lands = sum(1 for _, tl in deck if "land" in tl.lower())
    if lands < constraints.min_lands:
        out.append(ConstraintViolation(
            code="too_few_lands",
            detail=f"deck has {lands} lands, need ≥ {constraints.min_lands}",
        ))
    if lands > constraints.max_lands:
        out.append(ConstraintViolation(
            code="too_many_lands",
            detail=f"deck has {lands} lands, max {constraints.max_lands}",
        ))

    creatures = sum(1 for _, tl in deck if "creature" in tl.lower())
    if creatures < constraints.min_creatures:
        out.append(ConstraintViolation(
            code="too_few_creatures",
            detail=f"deck has {creatures} creatures, need ≥ {constraints.min_creatures}",
        ))

    # Playset cap. Singleton formats (Commander) limit non-basics to 1;
    # other constructed formats limit to 4. Basics are always uncapped.
    BASIC_NAMES = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes",
                   "Snow-Covered Plains", "Snow-Covered Island", "Snow-Covered Swamp",
                   "Snow-Covered Mountain", "Snow-Covered Forest"}
    cap = 1 if constraints.singleton else 4
    counts: dict[str, int] = {}
    for profile, _ in deck:
        counts[profile.name] = counts.get(profile.name, 0) + 1
    for name, count in counts.items():
        if count > cap and name not in BASIC_NAMES:
            out.append(ConstraintViolation(
                code="over_playset",
                detail=f"{name} has {count} copies (max {cap})",
            ))

    # Commander-specific: requires a commander_name; commander must be a
    # legendary creature (we trust caller for type, just check presence).
    if constraints.format_config.has_commander:
        if not constraints.commander_name:
            out.append(ConstraintViolation(
                code="missing_commander",
                detail="commander format requires a commander_name",
            ))

    return out


def is_legal(
    deck: list[tuple[CardProfile, str]],
    constraints: OptimizerConstraints,
    *,
    card_prices: dict[str, float] | None = None,
) -> bool:
    return not validate_constraints(deck, constraints, card_prices=card_prices)
