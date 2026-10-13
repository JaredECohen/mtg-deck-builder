from __future__ import annotations

from collections import Counter

from app.constants import (
    COMMANDER_DECK_SIZE,
    COMMANDER_LAND_FLOOR,
    COMMANDER_LAND_RANGE,
    CONSTRUCTED_DECK_SIZE,
    CONSTRUCTED_LAND_RANGE,
    ROLE_TAGS,
    SIDEBOARD_SIZE,
)
from app.models import CardRecord, CardRef, ScoreBreakdown, ValidateDeckRequest, ValidationResult
from app.rules import can_be_commander, copy_limit, is_basic_land, is_land_card
from app.services.card_repository import CardRepository


class DeckValidator:
    def __init__(self, repository: CardRepository) -> None:
        self.repository = repository

    def validate(self, request: ValidateDeckRequest) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        main_count = sum(card.quantity for card in request.mainboard)
        side_count = sum(card.quantity for card in request.sideboard)
        # Copies are counted across mainboard + sideboard (+ commander), keyed
        # by canonical card name, against each card's own copy limit.
        name_counter = Counter[str]()
        copy_limits: dict[str, int] = {}
        mainboard_land_count = 0
        commander_identity: set[str] = set()
        commander_resolved = False
        role_counts: Counter[str] = Counter()
        color_symbol_demand: Counter[str] = Counter()
        mana_value_buckets: Counter[int] = Counter()
        mana_source_count: Counter[str] = Counter()

        def validate_ref(ref: CardRef, *, count_mainboard_lands: bool) -> None:
            nonlocal mainboard_land_count
            card = self.repository.get_card(ref.name)
            if not card:
                errors.append(f"Unknown card: {ref.name}")
                return
            legality = card.legalities.get(request.format, "not_legal")
            if legality not in {"legal", "restricted"}:
                errors.append(f"{ref.name} is not legal in {request.format}.")

            if count_mainboard_lands and is_land_card(card):
                mainboard_land_count += ref.quantity
                if is_basic_land(card):
                    basic_color = self._basic_land_color(card.name)
                    if basic_color:
                        mana_source_count[basic_color] += ref.quantity
                else:
                    for color in card.color_identity or card.colors:
                        mana_source_count[color] += ref.quantity

            limit = copy_limit(card, request.format)
            if limit is not None:
                name_counter[card.name] += ref.quantity
                copy_limits[card.name] = limit

            if count_mainboard_lands:
                if not is_land_card(card):
                    mana_value_buckets[min(6, int(card.mana_value or 0))] += ref.quantity
                for role in self._card_roles(card):
                    role_counts[role] += ref.quantity
                for color in card.colors:
                    color_symbol_demand[color] += ref.quantity

        for ref in request.mainboard:
            validate_ref(ref, count_mainboard_lands=True)
        for ref in request.sideboard:
            validate_ref(ref, count_mainboard_lands=False)

        if request.format == "commander" and request.commander:
            commander_card = self.repository.get_card(request.commander)
            if not commander_card:
                errors.append(f"Unknown commander: {request.commander}")
            else:
                commander_legality = commander_card.legalities.get(request.format, "not_legal")
                if commander_legality not in {"legal", "restricted"}:
                    errors.append(f"{request.commander} is not legal in {request.format}.")
                if not can_be_commander(commander_card):
                    errors.append(f"{commander_card.name} can't be your commander (not a legendary creature).")
                commander_identity = set(commander_card.color_identity or commander_card.colors)
                commander_resolved = True
                # The commander is one of the deck's 100 cards, so a copy in
                # the 99 breaks singleton.
                commander_limit = copy_limit(commander_card, request.format)
                if commander_limit is not None:
                    name_counter[commander_card.name] += 1
                    copy_limits[commander_card.name] = commander_limit

        for name, quantity in name_counter.items():
            limit = copy_limits[name]
            if quantity <= limit:
                continue
            if request.format == "commander" and limit == 1:
                errors.append(f"{name} exceeds Commander singleton rules.")
            elif limit == 1:
                errors.append(f"{name} is restricted in {request.format} and may only appear once.")
            else:
                errors.append(f"{name} exceeds the {limit}-copy limit.")

        if request.format == "commander":
            if not request.commander:
                errors.append("Commander format requires a commander.")
            if main_count != COMMANDER_DECK_SIZE:
                errors.append(f"Commander decks must have exactly {COMMANDER_DECK_SIZE} cards in the mainboard.")
            if side_count != 0:
                warnings.append("Commander decks typically do not use a sideboard.")
            # An empty identity is meaningful: colorless commanders may only
            # contain colorless cards. Do not use truthiness as the gate.
            if commander_resolved:
                for ref in request.mainboard + request.sideboard:
                    card = self.repository.get_card(ref.name)
                    if not card:
                        continue
                    if not self.repository.fits_color_identity(card, commander_identity):
                        errors.append(f"{ref.name} falls outside the commander's color identity.")
        else:
            if main_count < CONSTRUCTED_DECK_SIZE:
                errors.append(f"Constructed decks must have at least {CONSTRUCTED_DECK_SIZE} cards in the mainboard.")
            if side_count > SIDEBOARD_SIZE:
                errors.append(f"Sideboards may have at most {SIDEBOARD_SIZE} cards (this one has {side_count}).")
            elif side_count not in {0, SIDEBOARD_SIZE}:
                warnings.append(f"Competitive constructed decks usually run a {SIDEBOARD_SIZE}-card sideboard.")

        mana_score = 100
        role_balance_score = 100
        synergy_score = 90
        competitiveness = 85
        curve_score = 100

        nonland_cards = sum(mana_value_buckets.values())
        avg_mana_value = (
            sum(value * count for value, count in mana_value_buckets.items()) / nonland_cards if nonland_cards else 0.0
        )
        min_lands, max_lands = self._recommended_land_range(request.format, avg_mana_value, main_count)
        if mainboard_land_count < min_lands:
            curve = f" for a curve averaging {avg_mana_value:.1f}" if request.format != "commander" else ""
            warnings.append(
                f"Land count looks low: selected {mainboard_land_count} lands, and {request.format} decks usually want at least {min_lands}{curve}."
            )
            mana_score -= 25 if request.format != "commander" else 15
        if mainboard_land_count > max_lands:
            warnings.append(
                f"Land count looks high: selected {mainboard_land_count} lands, and {request.format} decks usually stay at or below {max_lands}."
            )
            mana_score -= 12

        low_curve = mana_value_buckets[0] + mana_value_buckets[1] + mana_value_buckets[2]
        high_curve = mana_value_buckets[5] + mana_value_buckets[6]
        if request.format != "commander" and low_curve < 14:
            warnings.append("Low-curve density is thin; the deck may stumble before its core engine turns on.")
            curve_score -= 18
            competitiveness -= 8
        if request.format != "commander" and high_curve > 10:
            warnings.append("Too many expensive spells for a 60-card shell; trimming top-end would improve consistency.")
            curve_score -= 20
        if request.format == "commander" and role_counts["ramp"] < 8:
            warnings.append("Commander decks usually want more ramp; this list may start too slowly.")
            role_balance_score -= 15
        if request.format == "commander" and role_counts["advantage"] < 8:
            warnings.append("Commander decks usually want more repeatable card flow; draw package looks thin.")
            role_balance_score -= 12

        if role_counts["interaction"] < (6 if request.format != "commander" else 8):
            warnings.append("Interaction density is light for the format; the deck may fold to opposing haymakers.")
            role_balance_score -= 18
            competitiveness -= 10
        if role_counts["threat"] < (12 if request.format != "commander" else 18):
            warnings.append("Threat count is low; the deck may struggle to convert stabilization into wins.")
            role_balance_score -= 15
        if role_counts["engine"] + role_counts["payoff"] < (8 if request.format != "commander" else 10):
            warnings.append("Synergy package looks shallow; the list needs more payoffs or enablers to justify its theme.")
            synergy_score -= 18
        if len({card.name.lower() for card in request.mainboard}) < 8:
            warnings.append("Deck may be too redundant or underdeveloped.")
            synergy_score -= 10
            competitiveness -= 10

        for color, demand in color_symbol_demand.items():
            if demand >= 8 and mana_source_count[color] < 8:
                warnings.append(
                    f"Mana base may not support the deck's {color} requirements cleanly; only {mana_source_count[color]} likely sources were detected."
                )
                mana_score -= 10

        if request.sideboard and request.format != "commander":
            unique_sideboard = len({ref.name for ref in request.sideboard})
            if unique_sideboard < 5:
                warnings.append("Sideboard lacks diversity; it is unlikely to cover the format's major matchup classes.")
                competitiveness -= 8
        if request.format == "commander" and mainboard_land_count < COMMANDER_LAND_FLOOR:
            warnings.append("Commander mana base is under the usual land floor; package assembly should reserve more land slots.")
            mana_score -= 8

        legality_score = 100 if not errors else 0
        components = [
            legality_score,
            max(0, min(100, mana_score)),
            max(0, min(100, synergy_score)),
            max(0, min(100, competitiveness)),
            max(0, min(100, role_balance_score)),
            max(0, min(100, curve_score)),
        ]
        total = sum(components) // len(components)

        return ValidationResult(
            is_legal=not errors,
            errors=errors,
            warnings=warnings,
            score=ScoreBreakdown(
                legality=legality_score,
                mana=components[1],
                synergy=components[2],
                competitiveness=components[3],
                role_balance=components[4],
                curve=components[5],
                total=total,
            ),
        )

    # Land share of the main deck by average nonland mana value: Burn
    # (avg ~1.5) runs 18-20 lands, control (avg 3+) 24-27. A single range
    # flagged every 19-land aggro deck as "low".
    _LAND_SHARE_BY_CURVE = ((1.8, 0.27, 0.35), (2.4, 0.30, 0.38), (3.0, 0.35, 0.43), (99.0, 0.38, 0.47))

    @classmethod
    def _recommended_land_range(cls, format_name: str, avg_mana_value: float = 0.0, deck_size: int = 60) -> tuple[int, int]:
        if format_name == "commander":
            return COMMANDER_LAND_RANGE
        if avg_mana_value <= 0:
            return CONSTRUCTED_LAND_RANGE
        size = max(deck_size, 60)
        for ceiling, low, high in cls._LAND_SHARE_BY_CURVE:
            if avg_mana_value <= ceiling:
                return round(size * low), round(size * high)
        return CONSTRUCTED_LAND_RANGE

    @staticmethod
    def _basic_land_color(name: str) -> str | None:
        return {
            "Plains": "W",
            "Island": "U",
            "Swamp": "B",
            "Mountain": "R",
            "Forest": "G",
        }.get(name.removeprefix("Snow-Covered "))

    @staticmethod
    def _card_roles(card: CardRecord) -> set[str]:
        roles: set[str] = set()
        if is_land_card(card):
            return {"mana"}
        for tag in card.tags:
            role = ROLE_TAGS.get(tag)
            if role:
                roles.add(role)
        if not roles and "Creature" in card.type_line:
            roles.add("threat")
        if not roles:
            roles.add("flex")
        return roles
