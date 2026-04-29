from __future__ import annotations

import re

from app.models import CardRef, ParseDecklistRequest, ParsedDecklistResponse
from app.services.card_repository import CardRepository


MAINBOARD_MARKERS = {"main", "mainboard", "deck"}
SIDEBOARD_MARKERS = {"side", "sideboard"}
COMMANDER_MARKERS = {"commander"}


class DeckParserService:
    def __init__(self, repository: CardRepository) -> None:
        self.repository = repository

    def parse(self, request: ParseDecklistRequest) -> ParsedDecklistResponse:
        current_section = "mainboard"
        commander: str | None = None
        mainboard: list[CardRef] = []
        sideboard: list[CardRef] = []
        warnings: list[str] = []

        for raw_line in request.deck_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower().rstrip(":")
            if lowered in MAINBOARD_MARKERS:
                current_section = "mainboard"
                continue
            if lowered in SIDEBOARD_MARKERS:
                current_section = "sideboard"
                continue
            if lowered in COMMANDER_MARKERS:
                current_section = "commander"
                continue

            parsed = self._parse_line(line)
            if parsed is None:
                warnings.append(f"Could not parse line: {line}")
                continue
            quantity, name = parsed
            card = self.repository.get_card(name)
            resolved_name = card.name if card else name
            if current_section == "commander":
                commander = resolved_name
                continue
            target = mainboard if current_section == "mainboard" else sideboard
            target.append(CardRef(name=resolved_name, quantity=quantity))

        if request.format == "commander" and commander is None and mainboard:
            first = self.repository.get_card(mainboard[0].name)
            if first and self.repository.is_legal_commander(first):
                commander = mainboard.pop(0).name
                warnings.append("Assumed the first line was the commander because no Commander section was provided.")

        return ParsedDecklistResponse(
            format=request.format,
            commander=commander,
            mainboard=self._merge_duplicates(mainboard),
            sideboard=self._merge_duplicates(sideboard),
            warnings=warnings,
        )

    @staticmethod
    def _parse_line(line: str) -> tuple[int, str] | None:
        match = re.match(r"^(?:(SB):\s*)?(\d+)[xX]?\s+(.+)$", line, re.IGNORECASE)
        if match:
            _, quantity, name = match.groups()
            # Strip trailing Arena-style set annotation from standard quantity lines (e.g. "4 Lightning Bolt (M11) 163")
            name = re.sub(r"\s+\([A-Za-z0-9]+\)\s+\d+$", "", name).strip()
            return int(quantity), name
        # Arena export format: "Card Name (SET) CollectorNumber" — no leading quantity
        arena_match = re.match(r"^(.+?)\s+\([A-Za-z0-9]+\)\s+\d+$", line)
        if arena_match:
            return 1, arena_match.group(1).strip()
        return None

    @staticmethod
    def _merge_duplicates(cards: list[CardRef]) -> list[CardRef]:
        merged: dict[str, int] = {}
        for card in cards:
            merged[card.name] = merged.get(card.name, 0) + card.quantity
        return [CardRef(name=name, quantity=quantity) for name, quantity in merged.items()]
