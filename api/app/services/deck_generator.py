from __future__ import annotations

from collections import Counter

from app.models import (
    ArchetypeRecord,
    CardRecord,
    CardRef,
    DeckCardExplanation,
    DeckResponse,
    GenerateDeckRequest,
    ScoreBreakdown,
    ValidateDeckRequest,
)
from app.services.card_repository import CardRepository
from app.services.deck_validator import DeckValidator


ROLE_MAP = {
    "aggressive": "primary pressure",
    "aggro": "primary pressure",
    "spells": "spell-density engine",
    "prowess": "threat scaling payoff",
    "lifegain": "lifegain engine",
    "slivers": "tribal synergy piece",
    "interaction": "interaction",
    "land": "mana base",
    "ramp": "mana acceleration",
}

CANONICAL_TAGS = {
    "aggressive": "aggro",
    "aristocrats": "sacrifice",
    "artifacts": "artifact",
    "creatures": "creature",
    "life gain": "lifegain",
    "midrange": "midrange",
    "reanimator": "graveyard",
    "sacrifice": "sacrifice",
    "spellslinger": "spells",
    "tempo": "tempo",
    "tribal": "tribal",
}


class DeckGenerator:
    def __init__(self, repository: CardRepository, validator: DeckValidator) -> None:
        self.repository = repository
        self.validator = validator

    def generate(self, request: GenerateDeckRequest) -> DeckResponse:
        archetypes = self._retrieve_archetypes(request)
        base = archetypes[0] if archetypes else self._fallback_archetype(request)
        mainboard = self._adapt_mainboard(base, request)
        sideboard = self._adapt_sideboard(base, request, mainboard)
        commander = base.commander if request.format == "commander" else None

        validation = self.validator.validate(
            ValidateDeckRequest(
                format=request.format,
                mainboard=mainboard,
                sideboard=sideboard,
                commander=commander,
            )
        )

        title = self._build_title(request, base)
        deck_price = self._estimate_price(mainboard, sideboard, commander)
        warnings = validation.warnings[:]
        if request.budget is not None and deck_price is not None and deck_price > request.budget:
            warnings.append(
                f"Estimated deck price is about ${deck_price:.2f}, which is above the requested budget of ${request.budget:.2f}."
            )
        explanation = self._build_explanation(request, base, warnings, deck_price)
        card_notes = self._build_card_notes(mainboard)

        return DeckResponse(
            format=request.format,
            title=title,
            colors=request.colors or base.colors,
            commander=commander,
            strategy_summary=base.strategy,
            mainboard=mainboard,
            sideboard=sideboard,
            estimated_price_usd=deck_price,
            is_legal=validation.is_legal,
            validation_errors=validation.errors,
            score=validation.score,
            explanation=explanation,
            card_notes=card_notes,
            warnings=list(dict.fromkeys(warnings)),
            source_archetypes=[archetype.name for archetype in archetypes[:3]],
            selected_archetype=base,
        )

    def refine(self, deck: DeckResponse, prompt: str) -> DeckResponse:
        updated = deck.model_copy(deep=True)
        lower_prompt = prompt.lower()
        refinement_notes: list[str] = []
        deck_changed = False

        if updated.format != "commander":
            if "cheaper" in lower_prompt or "budget" in lower_prompt:
                mana_swaps = self._downgrade_expensive_mana_base(updated, max_swaps=6)
                spell_swaps = self._swap_expensive_spells_for_cheaper_options(updated, max_swaps=4)
                total_budget_swaps = mana_swaps + spell_swaps
                if total_budget_swaps:
                    deck_changed = True
                    refinement_notes.append(
                        f"Refinement bias: reduced premium costs with {total_budget_swaps} budget-oriented swap{'s' if total_budget_swaps != 1 else ''}."
                    )
                else:
                    refinement_notes.append("Refinement bias: looked for cheaper legal substitutes, but the current sample pool had no clean downgrade path.")
            if "control" in lower_prompt or "interaction" in lower_prompt:
                interaction_swaps = self._swap_basic_lands_for_candidates(
                    updated,
                    desired_tags={"interaction", "removal"},
                    max_swaps=2,
                )
                if interaction_swaps:
                    deck_changed = True
                    refinement_notes.append(
                        f"Refinement bias: converted {interaction_swaps} land slot{'s' if interaction_swaps != 1 else ''} into extra interaction."
                    )
                else:
                    refinement_notes.append("Refinement bias: no legal interaction upgrades were available beyond the current main deck and sideboard limits.")
            if "aggressive" in lower_prompt or "faster" in lower_prompt:
                speed_swaps = self._swap_basic_lands_for_candidates(
                    updated,
                    desired_tags={"aggro", "spells", "tempo"},
                    max_swaps=2,
                    max_mana_value=2,
                )
                if speed_swaps:
                    deck_changed = True
                    refinement_notes.append(
                        f"Refinement bias: trimmed {speed_swaps} mana source{'s' if speed_swaps != 1 else ''} for lower-curve threats or spells."
                    )
                else:
                    refinement_notes.append("Refinement bias: the sample card pool did not have additional low-curve threats that fit the deck's current constraints.")
        else:
            refinement_notes.append("Refinement bias: commander refinements are explanation-first for now because the local sample pool is still shallow.")

        validation = self.validator.validate(
            ValidateDeckRequest(
                format=updated.format,
                mainboard=updated.mainboard,
                sideboard=updated.sideboard,
                commander=updated.commander,
            )
        )
        updated.is_legal = validation.is_legal
        updated.validation_errors = validation.errors
        updated.warnings = validation.warnings
        updated.score = validation.score
        if ("cheaper" in lower_prompt or "budget" in lower_prompt) and deck_changed:
            updated.score.budget_fit = min(100, updated.score.budget_fit + 8)
        if ("control" in lower_prompt or "interaction" in lower_prompt) and deck_changed:
            updated.score.competitiveness = min(100, updated.score.competitiveness + 3)
        if ("aggressive" in lower_prompt or "faster" in lower_prompt) and deck_changed:
            updated.score.prompt_fit = min(100, updated.score.prompt_fit + 5)
        updated.score.total = (
            updated.score.legality
            + updated.score.mana
            + updated.score.synergy
            + updated.score.prompt_fit
            + updated.score.competitiveness
            + updated.score.budget_fit
        ) // 6
        updated.estimated_price_usd = self._estimate_price(updated.mainboard, updated.sideboard, updated.commander)
        updated.card_notes = self._build_card_notes(updated.mainboard)
        updated.explanation.extend(refinement_notes)

        updated.title = f"{deck.title} - Refined"
        return updated

    def export_plain(self, deck: DeckResponse) -> str:
        lines = [deck.title, f"Format: {deck.format}"]
        if deck.commander:
            lines.append(f"Commander: {deck.commander}")
        lines.append("")
        lines.append("Mainboard")
        for card in deck.mainboard:
            lines.append(f"{card.quantity} {card.name}")
        if deck.sideboard:
            lines.append("")
            lines.append("Sideboard")
            for card in deck.sideboard:
                lines.append(f"{card.quantity} {card.name}")
        return "\n".join(lines)

    def export(self, deck: DeckResponse, target: str) -> str:
        if target == "arena":
            return self._export_arena(deck)
        if target == "csv":
            return self._export_csv(deck)
        if target == "moxfield":
            return self._export_moxfield(deck)
        return self.export_plain(deck)

    def _retrieve_archetypes(self, request: GenerateDeckRequest) -> list[ArchetypeRecord]:
        requested_tags = {self._canonicalize_tag(tag) for tag in request.playstyle_tags + request.theme_tags}
        scored: list[tuple[int, ArchetypeRecord]] = []
        for archetype in self.repository.archetypes_for_format(request.format):
            score = 0
            if request.colors:
                requested_colors = set(request.colors)
                archetype_colors = set(archetype.colors)
                overlap = len(requested_colors & archetype_colors)
                score += overlap * 8
                if requested_colors and requested_colors.issubset(archetype_colors):
                    score += 12
                elif overlap == 0:
                    score -= 20
            tag_overlap = len(requested_tags & {self._canonicalize_tag(tag) for tag in archetype.tags})
            score += tag_overlap * 10
            if not request.colors:
                score += 5
            if not requested_tags:
                score += 5
            scored.append((score, archetype))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [archetype for _, archetype in scored] or []

    def _fallback_archetype(self, request: GenerateDeckRequest) -> ArchetypeRecord:
        archetypes = self.repository.archetypes_for_format(request.format)
        if archetypes:
            return archetypes[0]
        raise ValueError(f"No archetypes available for format {request.format}")

    def _adapt_mainboard(self, archetype: ArchetypeRecord, request: GenerateDeckRequest) -> list[CardRef]:
        if request.format == "commander":
            return self._build_commander_mainboard(archetype, request)

        filtered: list[CardRef] = []
        excluded = {card.lower() for card in request.exclude_cards}
        for ref in archetype.mainboard:
            if ref.name.lower() in excluded:
                continue
            if not self._matches_color_request(ref.name, request.colors):
                continue
            if not self._is_card_legal(ref.name, request.format):
                continue
            if not self._fits_budget_request(ref, request.budget):
                continue
            if self.repository.get_card(ref.name):
                filtered.append(ref)

        if request.include_cards:
            include_names = [name for name in request.include_cards if self.repository.get_card(name)]
            for name in include_names:
                if request.colors and not self._matches_color_request(name, request.colors):
                    continue
                if not self._is_card_legal(name, request.format):
                    continue
                filtered.insert(0, CardRef(name=name, quantity=1 if request.format == "commander" else 2))

        compacted = self._merge_refs(filtered, request.format)
        deck = self._normalize_constructed_counts(
            compacted,
            request.colors or archetype.colors,
            request.format,
            request.budget,
            excluded,
        )
        return deck

    def _adapt_sideboard(
        self,
        archetype: ArchetypeRecord,
        request: GenerateDeckRequest,
        mainboard: list[CardRef],
    ) -> list[CardRef]:
        if request.format == "commander":
            return []
        excluded = {card.lower() for card in request.exclude_cards}
        mainboard_counts = Counter({card.name: card.quantity for card in mainboard})
        allowed_cards: list[CardRef] = []
        for ref in archetype.sideboard:
            if not self._matches_color_request(ref.name, request.colors):
                continue
            if ref.name.lower() in excluded:
                continue
            if not self._is_card_legal(ref.name, request.format):
                continue
            card = self.repository.get_card(ref.name)
            if not card:
                continue
            if "Basic Land" in card.type_line:
                allowed_cards.append(ref)
                continue

            copy_limit = self._copy_limit(card, request.format) or ref.quantity
            remaining_copies = max(0, copy_limit - mainboard_counts[ref.name])
            if remaining_copies:
                allowed_cards.append(CardRef(name=ref.name, quantity=min(ref.quantity, remaining_copies)))

        compacted = self._merge_refs(allowed_cards, request.format)
        if sum(card.quantity for card in compacted) >= 15:
            return self._trim_to_total(compacted, 15)
        return self._pad_sideboard(compacted, 15, request.format, request.colors or archetype.colors, mainboard, excluded)

    def _build_commander_mainboard(self, archetype: ArchetypeRecord, request: GenerateDeckRequest) -> list[CardRef]:
        requested_colors = request.colors or archetype.colors
        commander_identity = self._commander_identity(archetype.commander, requested_colors)
        result = self._merge_refs(archetype.mainboard, request.format)
        known_names = {ref.name for ref in result}

        for card in self.repository.all_cards():
            if card.name == archetype.commander:
                continue
            if card.name in known_names:
                continue
            if not self._is_card_legal_record(card, request.format):
                continue
            if not self._fits_commander_identity(card, commander_identity):
                continue
            if requested_colors and not self._matches_color_request(card.name, requested_colors):
                continue
            result.append(CardRef(name=card.name, quantity=1))
            known_names.add(card.name)

        basic_land_names = self._basic_lands_for_colors(list(commander_identity or requested_colors))
        if not basic_land_names:
            basic_land_names = ["Mountain"]
        while sum(card.quantity for card in result) < 99:
            name = basic_land_names[(sum(card.quantity for card in result)) % len(basic_land_names)]
            result.append(CardRef(name=name, quantity=1))
        return self._trim_to_total(self._merge_refs(result, request.format), 99)

    def _merge_refs(self, refs: list[CardRef], format_name: str) -> list[CardRef]:
        counter = Counter[str]()
        for ref in refs:
            counter[ref.name] += ref.quantity
        merged: list[CardRef] = []
        for name, quantity in counter.items():
            card = self.repository.get_card(name)
            if not card or not self._is_card_legal_record(card, format_name):
                continue
            copy_limit = self._copy_limit(card, format_name)
            if copy_limit is not None:
                quantity = min(quantity, copy_limit)
            merged.append(CardRef(name=name, quantity=quantity))
        return merged

    def _normalize_constructed_counts(
        self,
        refs: list[CardRef],
        colors: list[str],
        format_name: str,
        budget: float | None,
        excluded_cards: set[str],
    ) -> list[CardRef]:
        total = sum(card.quantity for card in refs)
        refs = refs[:]
        if total > 60:
            return self._trim_to_total(refs, 60)
        padding_candidates = self._constructed_padding_candidates(format_name, colors, budget, excluded_cards)
        stalled_passes = 0
        while total < 60 and padding_candidates:
            added_this_pass = False
            merged = Counter[str]()
            for ref in refs:
                merged[ref.name] += ref.quantity
            for candidate_name in padding_candidates:
                card = self.repository.get_card(candidate_name)
                if not card:
                    continue
                copy_limit = self._copy_limit(card, format_name)
                current_quantity = merged[candidate_name]
                if copy_limit is not None and current_quantity >= copy_limit:
                    continue
                refs.append(CardRef(name=candidate_name, quantity=1))
                total += 1
                added_this_pass = True
                merged[candidate_name] += 1
                if total >= 60:
                    break
            if added_this_pass:
                stalled_passes = 0
            else:
                stalled_passes += 1
                if stalled_passes > 1:
                    break
        fallback_basics = self._basic_lands_for_colors(colors)
        while total < 60:
            land_name = fallback_basics[total % len(fallback_basics)]
            refs.append(CardRef(name=land_name, quantity=1))
            total += 1
        return self._merge_refs(refs, format_name)

    def _trim_to_total(self, refs: list[CardRef], target: int) -> list[CardRef]:
        result: list[CardRef] = []
        total = 0
        for ref in refs:
            if total >= target:
                break
            quantity = min(ref.quantity, target - total)
            result.append(CardRef(name=ref.name, quantity=quantity))
            total += quantity
        return result

    def _pad_sideboard(
        self,
        refs: list[CardRef],
        target: int,
        format_name: str,
        colors: list[str],
        mainboard: list[CardRef],
        excluded_cards: set[str],
    ) -> list[CardRef]:
        total = sum(card.quantity for card in refs)
        fallback_options = self._sideboard_fallbacks(format_name, colors, excluded_cards)
        mainboard_counts = Counter({card.name: card.quantity for card in mainboard})
        sideboard_counts = Counter({card.name: card.quantity for card in refs})
        stalled_passes = 0

        while total < target and fallback_options:
            added_this_pass = False
            for fallback_name in fallback_options:
                if total >= target:
                    break
                fallback_card = self.repository.get_card(fallback_name)
                if not fallback_card or not self._is_card_legal_record(fallback_card, format_name):
                    continue
                copy_limit = self._copy_limit(fallback_card, format_name)
                combined_quantity = mainboard_counts[fallback_name] + sideboard_counts[fallback_name]
                if copy_limit is not None and combined_quantity >= copy_limit:
                    continue
                sideboard_counts[fallback_name] += 1
                total += 1
                added_this_pass = True
            if added_this_pass:
                stalled_passes = 0
            else:
                stalled_passes += 1
                if stalled_passes > 1:
                    break

        fallback_basics = self._basic_lands_for_colors(colors)
        idx = 0
        while total < target and fallback_basics:
            fallback_name = fallback_basics[idx % len(fallback_basics)]
            sideboard_counts[fallback_name] += 1
            total += 1
            idx += 1
        return [CardRef(name=name, quantity=quantity) for name, quantity in sideboard_counts.items() if quantity > 0]

    def _build_title(self, request: GenerateDeckRequest, archetype: ArchetypeRecord) -> str:
        archetype_words = {word.lower() for word in archetype.name.replace("-", " ").split()}
        theme_parts: list[str] = []
        seen_tags: set[str] = set()
        for tag in request.theme_tags + request.playstyle_tags:
            normalized = tag.strip().lower()
            if not normalized or normalized in seen_tags or normalized in archetype_words:
                continue
            theme_parts.append(tag.title())
            seen_tags.add(normalized)
            if len(theme_parts) == 2:
                break
        theme = " ".join(theme_parts).strip()
        return f"{theme + ' ' if theme else ''}{archetype.name}".strip()

    def _build_explanation(
        self,
        request: GenerateDeckRequest,
        archetype: ArchetypeRecord,
        warnings: list[str],
        deck_price: float | None,
    ) -> list[str]:
        notes = [
            f"This list starts from the {archetype.name} shell because it best matches the requested {request.format} constraints.",
            "The generator keeps the core game plan intact, then adapts around colors, themes, and requested play patterns.",
            "Every list is passed through deterministic legality and deck-size validation before it is returned.",
        ]
        if request.playstyle_tags or request.theme_tags:
            notes.append(
                f"Prompt fit focus: {', '.join(request.playstyle_tags + request.theme_tags)}."
            )
        if request.budget is not None:
            notes.append(f"Budget target acknowledged at ${request.budget:.0f}; premium staples should be reviewed against live prices before purchase.")
        if deck_price is not None:
            notes.append(f"Estimated paper price from cached card data: about ${deck_price:.2f}.")
        if warnings:
            notes.append(f"Current warnings: {'; '.join(warnings)}")
        return notes

    def _build_card_notes(self, refs: list[CardRef]) -> list[DeckCardExplanation]:
        notes: list[DeckCardExplanation] = []
        for ref in refs[:10]:
            card = self.repository.get_card(ref.name)
            if not card:
                continue
            role = "flex slot"
            for tag in card.tags:
                if tag in ROLE_MAP:
                    role = ROLE_MAP[tag]
                    break
            notes.append(
                DeckCardExplanation(
                    name=ref.name,
                    role=role,
                    reason=f"Included as a {role} that supports the deck's core plan.",
                )
            )
        return notes

    @staticmethod
    def _canonicalize_tag(tag: str) -> str:
        normalized = tag.strip().lower()
        return CANONICAL_TAGS.get(normalized, normalized)

    def _is_card_legal_record(self, card: CardRecord, format_name: str) -> bool:
        return card.legalities.get(format_name, "not_legal") in {"legal", "restricted"}

    def _is_card_legal(self, card_name: str, format_name: str) -> bool:
        card = self.repository.get_card(card_name)
        return bool(card and self._is_card_legal_record(card, format_name))

    def _copy_limit(self, card: CardRecord, format_name: str) -> int | None:
        if "Basic Land" in card.type_line:
            return None
        legality = card.legalities.get(format_name, "not_legal")
        if format_name == "commander" or legality == "restricted":
            return 1
        return 4

    def _commander_identity(self, commander_name: str | None, fallback_colors: list[str]) -> set[str]:
        if not commander_name:
            return set(fallback_colors)
        commander = self.repository.get_card(commander_name)
        if not commander:
            return set(fallback_colors)
        return set(commander.color_identity or commander.colors or fallback_colors)

    @staticmethod
    def _fits_commander_identity(card: CardRecord, commander_identity: set[str]) -> bool:
        identity = set(card.color_identity or card.colors)
        return not identity or identity.issubset(commander_identity)

    def _matches_color_request(self, card_name: str, requested_colors: list[str]) -> bool:
        if not requested_colors:
            return True
        card = self.repository.get_card(card_name)
        if not card:
            return False
        identity = set(card.color_identity or card.colors)
        requested = set(requested_colors)
        return not identity or identity.issubset(requested)

    def _fits_budget_request(self, ref: CardRef, budget: float | None) -> bool:
        if budget is None:
            return True
        card = self.repository.get_card(ref.name)
        if not card or card.price_usd is None:
            return True
        per_card_cap = max(3.0, budget / 15.0)
        return card.price_usd <= per_card_cap or "Land" in card.type_line

    def _estimate_price(self, mainboard: list[CardRef], sideboard: list[CardRef], commander: str | None) -> float | None:
        total = 0.0
        priced_cards = 0
        for ref in mainboard + sideboard:
            card = self.repository.get_card(ref.name)
            if not card or card.price_usd is None:
                continue
            total += card.price_usd * ref.quantity
            priced_cards += 1
        if commander:
            commander_card = self.repository.get_card(commander)
            if commander_card and commander_card.price_usd is not None:
                total += commander_card.price_usd
                priced_cards += 1
        return round(total, 2) if priced_cards else None

    def _basic_lands_for_colors(self, colors: list[str]) -> list[str]:
        mapping = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
        lands = [mapping[color] for color in colors if color in mapping and self.repository.get_card(mapping[color])]
        if lands:
            return lands

        fallback_basics = [name for name in ("Plains", "Island", "Mountain", "Swamp", "Forest") if self.repository.get_card(name)]
        return fallback_basics or ["Mountain"]

    def _sideboard_fallbacks(self, format_name: str, colors: list[str], excluded_cards: set[str]) -> list[str]:
        scored: list[tuple[int, str]] = []
        for card in self.repository.all_cards():
            if card.name.lower() in excluded_cards:
                continue
            if not self._is_card_legal_record(card, format_name):
                continue
            if not self._matches_color_request(card.name, colors):
                continue
            if "Land" in card.type_line:
                continue
            score = 0
            if "interaction" in card.tags or "removal" in card.tags:
                score += 20
            if "tempo" in card.tags or "spells" in card.tags:
                score += 10
            score -= int(card.mana_value)
            scored.append((score, card.name))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        ordered: list[str] = []
        seen: set[str] = set()
        for _, name in scored:
            if name in seen:
                continue
            ordered.append(name)
            seen.add(name)
        for basic_land in self._basic_lands_for_colors(colors):
            if basic_land not in seen:
                ordered.append(basic_land)
        return ordered or ["Mountain"]

    def _downgrade_expensive_mana_base(self, deck: DeckResponse, max_swaps: int) -> int:
        counts, order = self._counts_from_refs(deck.mainboard)
        basic_lands = self._basic_lands_for_colors(deck.colors)
        if not basic_lands:
            return 0

        swaps = 0
        nonbasic_lands = sorted(
            (
                ref
                for ref in deck.mainboard
                if (card := self.repository.get_card(ref.name))
                and "Land" in card.type_line
                and "Basic Land" not in card.type_line
                and (card.price_usd or 0) > 0
            ),
            key=lambda ref: self.repository.get_card(ref.name).price_usd or 0,
            reverse=True,
        )
        for ref in nonbasic_lands:
            while counts[ref.name] > 0 and swaps < max_swaps:
                replacement_name = basic_lands[swaps % len(basic_lands)]
                counts[ref.name] -= 1
                if replacement_name not in order:
                    order.append(replacement_name)
                counts[replacement_name] += 1
                swaps += 1
            if swaps >= max_swaps:
                break

        if swaps:
            deck.mainboard = self._counts_to_refs(counts, order)
        return swaps

    def _swap_expensive_spells_for_cheaper_options(self, deck: DeckResponse, max_swaps: int) -> int:
        counts, order = self._counts_from_refs(deck.mainboard)
        swaps = 0
        candidates = self._constructed_padding_candidates(deck.format, deck.colors, None, set())
        expensive_refs = sorted(
            (
                ref
                for ref in deck.mainboard
                if (card := self.repository.get_card(ref.name))
                and "Land" not in card.type_line
                and (card.price_usd or 0) > 0
            ),
            key=lambda ref: self.repository.get_card(ref.name).price_usd or 0,
            reverse=True,
        )

        for ref in expensive_refs:
            current_card = self.repository.get_card(ref.name)
            if not current_card:
                continue
            replacement_name = self._find_cheaper_replacement(deck, counts, current_card, candidates)
            if not replacement_name:
                continue
            counts[ref.name] -= 1
            if replacement_name not in order:
                order.append(replacement_name)
            counts[replacement_name] += 1
            swaps += 1
            if swaps >= max_swaps:
                break

        if swaps:
            deck.mainboard = self._counts_to_refs(counts, order)
        return swaps

    def _find_cheaper_replacement(
        self,
        deck: DeckResponse,
        counts: Counter[str],
        current_card: CardRecord,
        candidates: list[str],
    ) -> str | None:
        current_price = current_card.price_usd or 0
        current_tags = set(current_card.tags)
        for candidate_name in candidates:
            if candidate_name == current_card.name:
                continue
            candidate = self.repository.get_card(candidate_name)
            if not candidate or "Land" in candidate.type_line:
                continue
            if (candidate.price_usd or 0) >= current_price:
                continue
            copy_limit = self._copy_limit(candidate, deck.format)
            if copy_limit is not None and counts[candidate.name] >= copy_limit:
                continue
            if current_tags and not current_tags.intersection(candidate.tags):
                continue
            return candidate.name
        return None

    def _swap_basic_lands_for_candidates(
        self,
        deck: DeckResponse,
        desired_tags: set[str],
        max_swaps: int,
        max_mana_value: int | None = None,
    ) -> int:
        counts, order = self._counts_from_refs(deck.mainboard)
        candidate_names = self._refinement_candidates(deck, desired_tags, max_mana_value)
        basic_lands = [name for name in self._basic_lands_for_colors(deck.colors) if counts[name] > 0]
        if not candidate_names or not basic_lands:
            return 0

        swaps = 0
        basic_index = 0
        for candidate_name in candidate_names:
            candidate = self.repository.get_card(candidate_name)
            if not candidate:
                continue
            copy_limit = self._copy_limit(candidate, deck.format)
            while swaps < max_swaps and basic_index < len(basic_lands):
                if copy_limit is not None and counts[candidate_name] >= copy_limit:
                    break
                land_name = basic_lands[basic_index]
                if counts[land_name] <= 0:
                    basic_index += 1
                    continue
                counts[land_name] -= 1
                if candidate_name not in order:
                    order.append(candidate_name)
                counts[candidate_name] += 1
                swaps += 1
                if counts[land_name] <= 0:
                    basic_index += 1
                if swaps >= max_swaps:
                    break
            if swaps >= max_swaps:
                break

        if swaps:
            deck.mainboard = self._counts_to_refs(counts, order)
        return swaps

    def _refinement_candidates(
        self,
        deck: DeckResponse,
        desired_tags: set[str],
        max_mana_value: int | None,
    ) -> list[str]:
        scored: list[tuple[int, str]] = []
        counts, _ = self._counts_from_refs(deck.mainboard)
        for card in self.repository.all_cards():
            if not self._is_card_legal_record(card, deck.format):
                continue
            if not self._matches_color_request(card.name, deck.colors):
                continue
            if "Land" in card.type_line:
                continue
            copy_limit = self._copy_limit(card, deck.format)
            if copy_limit is not None and counts[card.name] >= copy_limit:
                continue
            if max_mana_value is not None and card.mana_value > max_mana_value:
                continue
            if desired_tags and not desired_tags.intersection(card.tags):
                continue
            score = len(desired_tags.intersection(card.tags)) * 10
            score -= int(card.mana_value)
            scored.append((score, card.name))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        ordered: list[str] = []
        seen: set[str] = set()
        for _, name in scored:
            if name in seen:
                continue
            ordered.append(name)
            seen.add(name)
        return ordered

    @staticmethod
    def _counts_from_refs(refs: list[CardRef]) -> tuple[Counter[str], list[str]]:
        counts = Counter[str]()
        order: list[str] = []
        for ref in refs:
            if ref.name not in counts:
                order.append(ref.name)
            counts[ref.name] += ref.quantity
        return counts, order

    @staticmethod
    def _counts_to_refs(counts: Counter[str], order: list[str]) -> list[CardRef]:
        return [CardRef(name=name, quantity=counts[name]) for name in order if counts[name] > 0]

    def _constructed_padding_candidates(
        self,
        format_name: str,
        colors: list[str],
        budget: float | None,
        excluded_cards: set[str],
    ) -> list[str]:
        scored: list[tuple[int, str]] = []
        for card in self.repository.all_cards():
            if card.name.lower() in excluded_cards:
                continue
            if not self._is_card_legal_record(card, format_name):
                continue
            if "Land" in card.type_line:
                continue
            if not self._matches_color_request(card.name, colors):
                continue
            if budget is not None and not self._fits_budget_request(CardRef(name=card.name, quantity=1), budget):
                continue
            score = 0
            if "creature" in card.tags or "payoff" in card.tags:
                score += 8
            if "interaction" in card.tags or "spells" in card.tags:
                score += 5
            score -= int(card.mana_value)
            scored.append((score, card.name))

        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        ordered: list[str] = []
        seen: set[str] = set()
        for _, name in scored:
            if name in seen:
                continue
            ordered.append(name)
            seen.add(name)
        return ordered

    def _export_arena(self, deck: DeckResponse) -> str:
        lines = [deck.title, ""]
        if deck.commander:
            lines.append("Commander")
            lines.append(f"1 {deck.commander}")
            lines.append("")
        lines.append("Deck")
        for card in deck.mainboard:
            lines.append(f"{card.quantity} {card.name}")
        if deck.sideboard:
            lines.append("")
            lines.append("Sideboard")
            for card in deck.sideboard:
                lines.append(f"{card.quantity} {card.name}")
        return "\n".join(lines)

    def _export_csv(self, deck: DeckResponse) -> str:
        lines = ["section,quantity,name"]
        if deck.commander:
            lines.append(f"commander,1,{deck.commander}")
        lines.extend(f"mainboard,{card.quantity},{card.name}" for card in deck.mainboard)
        lines.extend(f"sideboard,{card.quantity},{card.name}" for card in deck.sideboard)
        return "\n".join(lines)

    def _export_moxfield(self, deck: DeckResponse) -> str:
        lines = [deck.title]
        if deck.commander:
            lines.append(f"Commander: 1 {deck.commander}")
        lines.append("Mainboard:")
        lines.extend(f"{card.quantity} {card.name}" for card in deck.mainboard)
        if deck.sideboard:
            lines.append("Sideboard:")
            lines.extend(f"{card.quantity} {card.name}" for card in deck.sideboard)
        return "\n".join(lines)
