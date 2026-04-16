from __future__ import annotations

from collections import Counter

from app.models import CardRef, ScoreBreakdown, ValidateDeckRequest, ValidationResult
from app.services.card_repository import CardRepository


class DeckValidator:
    def __init__(self, repository: CardRepository) -> None:
        self.repository = repository

    def validate(self, request: ValidateDeckRequest) -> ValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        main_count = sum(card.quantity for card in request.mainboard)
        side_count = sum(card.quantity for card in request.sideboard)
        name_counter = Counter[str]()
        mainboard_land_count = 0
        mana_score = 80
        synergy_score = 75
        prompt_fit = 80
        competitiveness = 75
        budget_fit = 85
        commander_identity: set[str] = set()

        def validate_ref(ref: CardRef, *, count_mainboard_lands: bool) -> None:
            nonlocal mainboard_land_count
            card = self.repository.get_card(ref.name)
            if not card:
                errors.append(f"Unknown card: {ref.name}")
                return
            legality = card.legalities.get(request.format, "not_legal")
            if legality not in {"legal", "restricted"}:
                errors.append(f"{ref.name} is not legal in {request.format}.")
            if legality == "restricted" and ref.quantity > 1:
                errors.append(f"{ref.name} is restricted in {request.format} and may only appear once.")
            if count_mainboard_lands and "Land" in card.type_line:
                mainboard_land_count += ref.quantity
            if request.format != "commander" and "Basic Land" not in card.type_line:
                name_counter[ref.name.lower()] += ref.quantity
            if request.format == "commander" and "Basic Land" not in card.type_line and ref.quantity > 1:
                errors.append(f"{ref.name} exceeds Commander singleton rules.")

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
                commander_identity = set(commander_card.color_identity or commander_card.colors)

        for name, quantity in name_counter.items():
            if quantity > 4:
                errors.append(f"{name.title()} exceeds the 4-copy limit.")

        if request.format == "commander":
            if not request.commander:
                errors.append("Commander format requires a commander.")
            if main_count != 99:
                errors.append("Commander decks must have exactly 99 cards in the mainboard.")
            if side_count != 0:
                warnings.append("Commander decks typically do not use a sideboard.")
            if commander_identity:
                for ref in request.mainboard + request.sideboard:
                    card = self.repository.get_card(ref.name)
                    if not card:
                        continue
                    identity = set(card.color_identity or card.colors)
                    if identity and not identity.issubset(commander_identity):
                        errors.append(f"{ref.name} falls outside the commander's color identity.")
        else:
            if main_count != 60:
                errors.append("Constructed decks must have exactly 60 cards in the mainboard.")
            if side_count not in {0, 15}:
                warnings.append("Competitive constructed decks usually run a 15-card sideboard.")

        min_lands, max_lands = self._recommended_land_range(request.format)
        if mainboard_land_count < min_lands:
            warnings.append(
                f"Land count looks low: selected {mainboard_land_count} lands, and {request.format} decks usually want at least {min_lands}."
            )
            mana_score -= 20 if request.format != "commander" else 15
        if mainboard_land_count > max_lands:
            warnings.append(
                f"Land count looks high: selected {mainboard_land_count} lands, and {request.format} decks usually stay at or below {max_lands}."
            )
            mana_score -= 10

        if len({card.name.lower() for card in request.mainboard}) < 8:
            warnings.append("Deck may be too redundant or underdeveloped.")
            synergy_score -= 10
            competitiveness -= 10

        legality_score = 100 if not errors else 0
        total = max(0, legality_score + mana_score + synergy_score + prompt_fit + competitiveness + budget_fit) // 6

        return ValidationResult(
            is_legal=not errors,
            errors=errors,
            warnings=warnings,
            score=ScoreBreakdown(
                legality=legality_score,
                mana=mana_score,
                synergy=synergy_score,
                prompt_fit=prompt_fit,
                competitiveness=competitiveness,
                budget_fit=budget_fit,
                total=total,
            ),
        )

    @staticmethod
    def _recommended_land_range(format_name: str) -> tuple[int, int]:
        if format_name == "commander":
            return 34, 40
        return 20, 28
