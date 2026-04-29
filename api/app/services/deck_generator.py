from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.models import (
    ArchetypeMetadata,
    ArchetypePackage,
    ArchetypeRecord,
    CardRecord,
    CardRef,
    CommanderPackageSummary,
    DeckCardExplanation,
    DeckMechanic,
    DeckProvenance,
    DeckResponse,
    DeckRoleSummary,
    DeckSectionSummary,
    GenerateDeckRequest,
    ManaCurvePoint,
    ValidateDeckRequest,
)
from app.constants import (
    CANONICAL_TAGS,
    COMMANDER_DECK_SIZE,
    COMMANDER_LAND_FLOOR,
    COMMANDER_ROLE_TARGETS,
    CONSTRUCTED_DECK_SIZE,
    LAND_TARGET_AGGRO,
    LAND_TARGET_COMMANDER,
    LAND_TARGET_DEFAULT,
    LAND_TARGET_RAMP,
    ROLE_MAP,
    SIDEBOARD_SIZE,
    THEME_TO_TAGS,
)
from app.services.card_repository import CardRepository
from app.services.deck_validator import DeckValidator
from app.services.llm_service import RefinementIntent, interpret_generate_prompt, interpret_refinement


@dataclass
class _RetrievalOutcome:
    """Outcome of retrieving archetype context for a generation request.

    Keeps the commander path's provenance separate from generic format
    fallbacks so an explicit narrow-color commander can never inherit a
    Sliver-shaped retrieval label.
    """

    base: ArchetypeRecord
    candidates: list[ArchetypeRecord]
    source_type: str  # "corpus" | "fallback"
    confidence: float
    evidence_count: int
    retrieved_from: list[str]
    fallback_used: bool
    notes: list[str] = field(default_factory=list)


class DeckGenerator:
    def __init__(self, repository: CardRepository, validator: DeckValidator) -> None:
        self.repository = repository
        self.validator = validator

    def generate(self, request: GenerateDeckRequest) -> DeckResponse:
        if request.prompt:
            intent = interpret_generate_prompt(request.prompt)
            request = request.model_copy(update={
                "colors": request.colors or intent.colors,
                "playstyle_tags": list(dict.fromkeys(request.playstyle_tags + intent.playstyle_tags)),
                "theme_tags": list(dict.fromkeys(request.theme_tags + intent.theme_tags)),
                "budget": request.budget if request.budget is not None else intent.budget,
                "commander_name": request.commander_name or intent.commander_name,
                "include_cards": list(dict.fromkeys(request.include_cards + intent.include_cards)),
                "exclude_cards": list(dict.fromkeys(request.exclude_cards + intent.exclude_cards)),
            })
        requested_tags = [self._canonicalize_tag(tag) for tag in request.playstyle_tags + request.theme_tags]
        include_warnings: list[str] = self._check_include_cards(request)
        commander_reason: str | None = None
        legality_actions: list[str] = []

        if request.format == "commander":
            outcome, commander, commander_reason, commander_identity = self._build_commander_context(request, requested_tags)
            base = outcome.base
            colors = self._ordered_commander_identity(commander, list(commander_identity))
            mainboard = self._build_commander_mainboard(base, request, list(commander_identity), requested_tags, commander)
            mainboard, legality_actions = self._enforce_commander_color_identity(mainboard, commander_identity)
            sideboard: list[CardRef] = []
        else:
            outcome = self._retrieve_for_constructed(request)
            base = outcome.base
            colors = request.colors or base.colors
            commander = None
            mainboard = self._build_constructed_mainboard(base, request, colors, requested_tags)
            sideboard = self._build_sideboard(base, request, colors, requested_tags, mainboard)
            commander_identity = set(colors)

        validation = self.validator.validate(
            ValidateDeckRequest(format=request.format, mainboard=mainboard, sideboard=sideboard, commander=commander)
        )
        estimated_price = self._estimate_price(mainboard, sideboard, commander)
        warnings = validation.warnings[:] + include_warnings + legality_actions
        if request.budget is not None and estimated_price is not None and estimated_price > request.budget:
            warnings.append(
                f"Estimated deck price is about ${estimated_price:.2f}, which is above the requested budget of ${request.budget:.2f}."
            )

        explanation = self._build_explanation(base, request, colors, mainboard, sideboard, warnings, commander_reason, outcome)
        mechanics = self._build_mechanics(mainboard, commander)
        role_summary = self._build_role_summary(mainboard)
        sections = self._build_sections(base, request, mainboard, sideboard, commander, warnings, commander_reason, outcome)
        mana_curve = self._build_mana_curve(mainboard)
        card_notes = self._build_card_notes(mainboard)

        provenance = DeckProvenance(
            source_type=outcome.source_type,
            confidence=round(outcome.confidence, 3),
            evidence_count=outcome.evidence_count,
            retrieved_from=outcome.retrieved_from,
            fallback_used=outcome.fallback_used,
            notes=outcome.notes,
        )

        # Final hard legality gate for commander format. The validator already
        # ran but if it surfaced color-identity errors we treat those as a
        # generation bug, not a deck-quality warning, and refuse to lie about
        # legality even if a basic land had to be substituted in.
        if request.format == "commander" and legality_actions:
            warnings.insert(0, "Generator substituted off-color cards with basic lands to honor commander color identity.")

        return DeckResponse(
            format=request.format,
            title=self._build_title(request, base, commander),
            colors=colors,
            commander=commander,
            strategy_summary=base.strategy,
            mainboard=mainboard,
            sideboard=sideboard,
            estimated_price_usd=estimated_price,
            is_legal=validation.is_legal,
            validation_errors=validation.errors,
            score=validation.score,
            explanation=explanation,
            card_notes=card_notes,
            sections=sections,
            mechanics=mechanics,
            role_summary=role_summary,
            mana_curve=mana_curve,
            warnings=list(dict.fromkeys(warnings)),
            source_archetypes=outcome.retrieved_from[:3],
            selected_archetype=base if outcome.source_type != "fallback" else None,
            provenance=provenance,
            playstyle_tags=request.playstyle_tags,
            theme_tags=request.theme_tags,
            card_types=self.repository.card_types_for(mainboard + sideboard, commander),
        )

    # ── Retrieval ────────────────────────────────────────────────────────

    def _retrieve_for_constructed(self, request: GenerateDeckRequest) -> _RetrievalOutcome:
        # Strict color subset first — stops a 4C shell from beating a 2C match.
        candidates = self.repository.top_archetypes(
            format_name=request.format,
            colors=request.colors,
            theme_tags=request.playstyle_tags + request.theme_tags,
            limit=8,
            strict_colors=True,
        )
        if candidates:
            base = candidates[0]
            evidence = sum(max(1, archetype.source_count) for archetype in candidates[:3])
            confidence = min(1.0, 0.4 + 0.1 * len(candidates) + 0.05 * min(10, base.source_count))
            return _RetrievalOutcome(
                base=base,
                candidates=candidates,
                source_type="corpus",
                confidence=confidence,
                evidence_count=evidence,
                retrieved_from=[archetype.name for archetype in candidates[:3]],
                fallback_used=False,
                notes=[],
            )
        # Soft fallback: relax color subset to overlap. Mark as hybrid so the
        # response still tells the user the corpus only partially matched.
        soft_candidates = self.repository.top_archetypes(
            format_name=request.format,
            colors=request.colors,
            theme_tags=request.playstyle_tags + request.theme_tags,
            limit=8,
            strict_colors=False,
        )
        if soft_candidates:
            base = soft_candidates[0]
            evidence = sum(max(1, archetype.source_count) for archetype in soft_candidates[:3])
            return _RetrievalOutcome(
                base=base,
                candidates=soft_candidates,
                source_type="hybrid",
                confidence=min(0.55, 0.3 + 0.05 * len(soft_candidates)),
                evidence_count=evidence,
                retrieved_from=[archetype.name for archetype in soft_candidates[:3]],
                fallback_used=True,
                notes=[
                    "No corpus archetype matched the requested colors strictly; using overlap-ranked shells whose color identity is broader than the request.",
                ],
            )
        all_archetypes = self.repository.archetypes_for_format(request.format)
        if not all_archetypes:
            raise ValueError(f"No archetypes available for format {request.format}")
        base = all_archetypes[0]
        return _RetrievalOutcome(
            base=base,
            candidates=all_archetypes[:3],
            source_type="fallback",
            confidence=0.25,
            evidence_count=base.source_count,
            retrieved_from=[base.name],
            fallback_used=True,
            notes=["No archetype matched the requested colors/themes; defaulted to a generic format shell."],
        )

    def _build_commander_context(
        self,
        request: GenerateDeckRequest,
        requested_tags: list[str],
    ) -> tuple[_RetrievalOutcome, str | None, str | None, set[str]]:
        """Build commander-specific retrieval, separated from constructed paths.

        For an explicit commander we never inherit unrelated format fallbacks —
        the colors and shell are derived purely from the named commander's
        identity.
        """
        if request.commander_name:
            commander, reason, base, outcome = self._explicit_commander_context(request)
            commander_identity = self._commander_identity(commander, list(outcome.base.colors))
            return outcome, commander, reason, commander_identity

        # Recommend mode: use generic format retrieval as a fallback shell, but
        # let _select_commander pick the actual commander from corpus packages.
        constructed_outcome = self._retrieve_for_constructed(request)
        commander, reason, archetype = self._select_commander(
            constructed_outcome.base,
            request,
            request.colors or constructed_outcome.base.colors,
            requested_tags,
        )
        commander_identity = self._commander_identity(commander, list(archetype.colors or constructed_outcome.base.colors))
        if archetype is constructed_outcome.base:
            outcome = constructed_outcome
        else:
            outcome = _RetrievalOutcome(
                base=archetype,
                candidates=[archetype],
                source_type="corpus",
                confidence=min(1.0, 0.55 + 0.05 * min(8, archetype.source_count)),
                evidence_count=max(archetype.source_count, 1),
                retrieved_from=[archetype.name],
                fallback_used=False,
                notes=["Commander selected from corpus packages."],
            )
        return outcome, commander, reason, commander_identity

    def _explicit_commander_context(
        self, request: GenerateDeckRequest
    ) -> tuple[str, str, ArchetypeRecord, _RetrievalOutcome]:
        if not request.commander_name:
            raise ValueError("A commander name is required for explicit commander selection.")
        profile = self.repository.get_commander_profile(request.commander_name)
        if not profile:
            raise ValueError(f"{request.commander_name} is not a legal commander in the local card corpus.")
        identity = list(profile.colors or [])
        exact_matches = self.repository.commander_archetypes_for_name(profile.card.name)
        if exact_matches:
            selected = sorted(exact_matches, key=lambda archetype: archetype.source_count, reverse=True)[0]
            confidence = min(1.0, 0.7 + 0.05 * min(6, selected.source_count))
            outcome = _RetrievalOutcome(
                base=selected,
                candidates=exact_matches,
                source_type="corpus",
                confidence=confidence,
                evidence_count=sum(max(1, archetype.source_count) for archetype in exact_matches),
                retrieved_from=[archetype.name for archetype in exact_matches[:3]],
                fallback_used=False,
                notes=[f"Found {len(exact_matches)} corpus archetype(s) keyed to {profile.card.name}."],
            )
            reason = (
                f"Selected {profile.card.name} because you explicitly chose it. "
                f"Found {len(exact_matches)} archetype shell(s) for this commander in the corpus."
            )
            return profile.card.name, reason, selected, outcome

        # Fallback: build a synthetic shell strictly from the commander profile
        # — never reuse unrelated retrieved archetypes.
        synthetic = ArchetypeRecord(
            id=f"commander::{profile.card.name.lower().replace(' ', '-')}",
            name=f"{profile.card.name} Commander Shell",
            format="commander",
            colors=identity,
            tags=profile.tags,
            strategy=profile.strategy_summary,
            commander=profile.card.name,
            mainboard=[],
            sideboard=[],
            source_count=0,
            avg_placement=None,
            metadata=ArchetypeMetadata(
                archetype_type="commander",
                color_profile=identity,
                core_cards=profile.signature_cards,
                flex_cards=profile.synergy_packages,
                land_packages=profile.land_package,
                commander_package=self._profile_to_commander_package(profile),
            ),
        )
        outcome = _RetrievalOutcome(
            base=synthetic,
            candidates=[],
            source_type="fallback",
            confidence=0.35,
            evidence_count=0,
            retrieved_from=[],
            fallback_used=True,
            notes=[
                f"No corpus archetype is keyed to {profile.card.name}; synthesized a deck from its color identity and inferred role packages.",
            ],
        )
        reason = (
            f"Selected {profile.card.name} because you explicitly chose it. "
            f"No corpus shell exists for this commander — the build was synthesized from its "
            f"color identity ({''.join(identity) or 'colorless'}) and inferred role packages."
        )
        return profile.card.name, reason, synthetic, outcome

    def _enforce_commander_color_identity(
        self,
        mainboard: list[CardRef],
        commander_identity: set[str],
    ) -> tuple[list[CardRef], list[str]]:
        """Strip any off-color card from a commander mainboard and patch with basics.

        This is the last line of defense: even if upstream package selection
        leaks a wrong-color card, this method guarantees the response is legal
        with respect to color identity.
        """
        cleaned: list[CardRef] = []
        removed_total = 0
        actions: list[str] = []
        for ref in mainboard:
            card = self.repository.get_card(ref.name)
            if card and not self.repository.fits_color_identity(card, commander_identity):
                removed_total += ref.quantity
                actions.append(f"Removed {ref.quantity}× {ref.name} (color identity {''.join(card.color_identity or card.colors)} not in commander identity).")
                continue
            cleaned.append(ref)
        if removed_total <= 0:
            return cleaned, actions
        # Re-fill the deck back to 99 with on-identity basic lands.
        counts: Counter[str] = Counter()
        for ref in cleaned:
            counts[ref.name] += ref.quantity
        basics = self._basic_lands_for_identity(commander_identity)
        index = 0
        while sum(counts.values()) < COMMANDER_DECK_SIZE and basics:
            counts[basics[index % len(basics)]] += 1
            index += 1
        return self._counts_to_refs(counts), actions

    def _basic_lands_for_identity(self, identity: set[str]) -> list[str]:
        """Return basic lands strictly within a commander's color identity.

        This is a stricter form of `_basic_lands_for_colors` — it never falls
        back to all five basics when the input is empty, because for commander
        decks an empty identity means colorless and Wastes is the only legal
        basic.
        """
        mapping = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
        ordered = sorted(identity)  # deterministic
        lands = [mapping[color] for color in ordered if color in mapping and self.repository.get_card(mapping[color])]
        if lands:
            return lands
        wastes = self.repository.get_card("Wastes")
        return ["Wastes"] if wastes else []

    def refine(self, deck: DeckResponse, prompt: str) -> DeckResponse:
        intent = interpret_refinement(prompt)

        current_price = deck.estimated_price_usd or 0
        if intent.budget is not None:
            budget: float | None = intent.budget
        elif intent.scale_budget_by is not None and current_price > 0:
            budget = current_price * intent.scale_budget_by
        else:
            budget = None

        original_tags = deck.playstyle_tags or ["midrange"]
        playstyle_tags = [t for t in original_tags if t not in intent.remove_playstyle_tags]
        for tag in intent.add_playstyle_tags:
            if tag not in playstyle_tags:
                playstyle_tags.append(tag)
        if not playstyle_tags:
            playstyle_tags = ["midrange"]

        commander_lower = (deck.commander or "").lower()
        exclude_set = {name.lower() for name in intent.exclude_cards}
        seed_cards = [
            ref for ref in deck.mainboard
            if ref.name.lower() != commander_lower and ref.name.lower() not in exclude_set
        ]
        for name in intent.include_cards:
            if not any(ref.name.lower() == name.lower() for ref in seed_cards):
                resolved = self.repository.get_card(name)
                seed_cards.append(CardRef(name=resolved.name if resolved else name, quantity=1))

        colors = list(dict.fromkeys(deck.colors + intent.color_changes))

        forced_includes = ([deck.commander] if deck.commander else []) + intent.include_cards

        request = GenerateDeckRequest(
            format=deck.format,
            colors=colors,
            playstyle_tags=playstyle_tags,
            theme_tags=deck.theme_tags or [],
            budget=budget,
            commander_name=deck.commander,
            include_cards=list(dict.fromkeys(forced_includes)),
            seed_cards=seed_cards,
            mode="constraint-aware",
            experience_level="beginner",
        )
        regenerated = self.generate(request)
        base_title = re.sub(r"( - Refined)+$", "", deck.title)
        regenerated.title = f"{base_title} - Refined"
        if prompt:
            regenerated.explanation.append(f"Refinement applied: {prompt}")
        return regenerated

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

    def _build_constructed_mainboard(
        self,
        archetype: ArchetypeRecord,
        request: GenerateDeckRequest,
        colors: list[str],
        requested_tags: list[str],
    ) -> list[CardRef]:
        excluded = {name.lower() for name in request.exclude_cards}
        counts = Counter[str]()
        core_names = {package.name for package in archetype.metadata.core_cards[:18]}

        for ref in archetype.mainboard:
            card = self.repository.get_card(ref.name)
            if not card or ref.name.lower() in excluded:
                continue
            if not self._is_card_legal_record(card, request.format) or not self._matches_color_request(card, colors):
                continue
            if not self._fits_budget_request(card, request.budget):
                continue
            desired_qty = max(ref.quantity, 2 if ref.name in core_names and "Land" not in card.type_line else ref.quantity)
            counts[card.name] = min(desired_qty, self._copy_limit(card, request.format) or desired_qty)

        for include_name in request.include_cards:
            card = self.repository.get_card(include_name)
            if card and self._matches_color_request(card, colors) and self._is_card_legal_record(card, request.format):
                counts[card.name] = max(counts[card.name], 2)

        # Seed from prior deck (refine path): preserve original quantities for cards that still pass all filters
        for ref in request.seed_cards:
            card = self.repository.get_card(ref.name)
            if not card or ref.name.lower() in excluded or "Land" in card.type_line:
                continue
            if not self._is_card_legal_record(card, request.format) or not self._matches_color_request(card, colors):
                continue
            if not self._fits_budget_request(card, request.budget):
                continue
            limit = self._copy_limit(card, request.format)
            counts[card.name] = min(ref.quantity, limit or ref.quantity)

        target_lands = self._target_land_count(archetype, requested_tags)
        package_candidates = self.repository.card_packages_by_role_theme(
            format_name=request.format,
            role="engine",
            theme_tags=requested_tags,
            limit=20,
        )
        ranked_candidates = [item["name"] for item in package_candidates] + self._rank_cards(request.format, colors, requested_tags, request.budget, excluded)
        nonland_target = CONSTRUCTED_DECK_SIZE - target_lands
        while self._nonland_total(counts) < nonland_target:
            if not self._add_ranked_candidate(counts, ranked_candidates, request.format, colors, request.budget, excluded):
                break
        self._add_lands_from_packages(counts, colors, target_lands, archetype.metadata.land_packages, request.format)
        while self._total_cards(counts) > CONSTRUCTED_DECK_SIZE:
            self._trim_excess_land_or_spell(counts, colors)
        max_fill_iters = 200
        for _ in range(max_fill_iters):
            if self._total_cards(counts) >= CONSTRUCTED_DECK_SIZE:
                break
            self._add_best_remaining(counts, ranked_candidates, request.format)
        return self._counts_to_refs(counts)

    def _build_sideboard(
        self,
        archetype: ArchetypeRecord,
        request: GenerateDeckRequest,
        colors: list[str],
        requested_tags: list[str],
        mainboard: list[CardRef],
    ) -> list[CardRef]:
        counts = Counter[str]()
        main_counts: Counter[str] = Counter()
        for ref in mainboard:
            resolved = self.repository.get_card(ref.name)
            main_counts[resolved.name if resolved else ref.name] += ref.quantity
        preferred_packages = archetype.metadata.sideboard_packages or archetype.metadata.matchup_tech_packages
        for package in preferred_packages:
            card = self.repository.get_card(package.name)
            if not card or not self._matches_color_request(card, colors):
                continue
            if not self._is_card_legal_record(card, request.format):
                continue
            remaining = max(0, (self._copy_limit(card, request.format) or 4) - main_counts[card.name])
            if remaining:
                counts[card.name] = min(int(round(package.average_quantity or 1)), remaining)

        fallback_names = [item["name"] for item in self.repository.card_packages_by_role_theme(format_name=request.format, role="interaction", theme_tags=requested_tags, limit=20)]
        while self._total_cards(counts) < SIDEBOARD_SIZE:
            if not self._add_ranked_candidate(counts, fallback_names, request.format, colors, request.budget, set(), main_counts):
                break
        while self._total_cards(counts) < SIDEBOARD_SIZE:
            for basic_land in self._basic_lands_for_colors(colors):
                counts[basic_land] += 1
                if self._total_cards(counts) >= SIDEBOARD_SIZE:
                    break
        return self._counts_to_refs(counts)

    def _select_commander(
        self,
        archetype: ArchetypeRecord,
        request: GenerateDeckRequest,
        colors: list[str],
        requested_tags: list[str],
    ) -> tuple[str | None, str | None, ArchetypeRecord]:
        candidates = self.repository.candidate_commander_packages(colors=colors, theme_tags=requested_tags, limit=6)
        # Hard-filter: a chosen commander must satisfy any explicit color
        # request the user passed in. A 5-color Sliver shell can never satisfy
        # a mono-W request, even if its support depth is overwhelming.
        requested_set = {color for color in colors if color and color != "C"} if colors else set()
        if requested_set:
            candidates = [c for c in candidates if set(c.colors).issubset(requested_set)]
        archetype_commander_card = self.repository.get_card(archetype.commander) if archetype.commander else None
        archetype_commander_ok = (
            archetype_commander_card is not None
            and self.repository.is_legal_commander(archetype_commander_card)
            and (not requested_set or self.repository.fits_color_identity(archetype_commander_card, requested_set))
        )
        if not candidates and archetype_commander_ok and archetype.commander:
            return archetype.commander, f"Selected {archetype.commander} because no stronger commander corpus match was available.", archetype
        best_score = float("-inf")
        best_choice: ArchetypeRecord | None = None
        best_reason = ""
        requested_color_set = set(colors)
        requested_tag_set = set(requested_tags)
        for candidate in candidates:
            package = candidate.metadata.commander_package
            if not candidate.commander or package is None:
                continue
            color_fit = len(requested_color_set & set(candidate.colors))
            exact_color_fit = requested_color_set.issubset(set(candidate.colors)) if requested_color_set else True
            theme_fit = len(requested_tag_set & {self._canonicalize_tag(tag) for tag in candidate.tags})
            support_depth = package.support_depth
            package_tags = {self._canonicalize_tag(tag) for pkg in package.synergy_packages for tag in pkg.tags}
            package_fit = len(requested_tag_set & package_tags)
            mechanical_coherence = len(package.signature_cards) + len(package.ramp_package) + len(package.draw_package) + len(package.interaction_package)
            score = color_fit * 8 + theme_fit * 12 + package_fit * 8 + support_depth * 2 + mechanical_coherence * 0.5
            if exact_color_fit:
                score += 12
            if request.include_cards and candidate.commander in request.include_cards:
                score += 25
            if score > best_score:
                best_score = score
                best_choice = candidate
                best_reason = (
                    f"Selected {candidate.commander} for color fit ({color_fit}), theme fit ({theme_fit}), "
                    f"support depth ({support_depth}), and commander package coherence ({mechanical_coherence:.0f})."
                )
        pool_commander, pool_reason = self._best_card_pool_commander(colors, requested_tags)
        if pool_commander is not None:
            pool_score = 18 + len(requested_color_set & set(self._commander_identity(pool_commander, colors))) * 8
            pool_score += len(requested_tag_set & {self._canonicalize_tag(tag) for tag in (self.repository.get_card(pool_commander).tags if self.repository.get_card(pool_commander) else [])}) * 8
            if pool_score > best_score:
                return pool_commander, pool_reason, archetype
        if best_choice:
            return best_choice.commander, best_reason, best_choice
        # If we still have nothing and the archetype's commander would violate
        # the requested color identity, refuse to silently expand the deck's
        # colors. Hand back the pool commander even if its score was low.
        if pool_commander is not None:
            return pool_commander, pool_reason, archetype
        if archetype_commander_ok:
            return archetype.commander, None, archetype
        return None, None, archetype

    def _build_commander_mainboard(
        self,
        archetype: ArchetypeRecord,
        request: GenerateDeckRequest,
        colors: list[str],
        requested_tags: list[str],
        commander: str | None,
    ) -> list[CardRef]:
        counts = Counter[str]()
        commander_identity = self._commander_identity(commander, colors)
        excluded = {name.lower() for name in request.exclude_cards}
        package = archetype.metadata.commander_package
        if package:
            self._add_package_cards(counts, package.ramp_package, target=COMMANDER_ROLE_TARGETS["ramp"], format_name=request.format, colors=list(commander_identity), excluded=excluded)
            self._add_package_cards(counts, package.draw_package, target=COMMANDER_ROLE_TARGETS["draw"], format_name=request.format, colors=list(commander_identity), excluded=excluded)
            self._add_package_cards(counts, package.interaction_package, target=COMMANDER_ROLE_TARGETS["interaction"], format_name=request.format, colors=list(commander_identity), excluded=excluded)
            self._add_package_cards(counts, package.synergy_packages, target=COMMANDER_ROLE_TARGETS["engine"], format_name=request.format, colors=list(commander_identity), excluded=excluded)
            self._add_package_cards(counts, package.signature_cards, target=COMMANDER_ROLE_TARGETS["payoff"], format_name=request.format, colors=list(commander_identity), excluded=excluded)

        # Seed from prior deck (refine path): preserve original quantities for cards that pass all filters
        for ref in request.seed_cards:
            card = self.repository.get_card(ref.name)
            if not card or ref.name.lower() in excluded or "Land" in card.type_line:
                continue
            if card.name == commander:
                continue
            if not self._is_card_legal_record(card, request.format):
                continue
            if not self.repository.fits_color_identity(card, commander_identity):
                continue
            if not self._fits_budget_request(card, request.budget):
                continue
            if counts[card.name] == 0:
                counts[card.name] = 1  # Commander format is singleton; skip if already added from packages

        themed_candidates = [item["name"] for item in self.repository.card_packages_by_role_theme(format_name=request.format, role="engine", theme_tags=requested_tags, limit=30)]
        fallback_ranked = self._rank_cards(request.format, list(commander_identity), requested_tags or ["ramp"], request.budget, excluded)
        seen = set()
        ranked_nonlands = []
        for name in themed_candidates + fallback_ranked:
            if name in seen:
                continue
            seen.add(name)
            ranked_nonlands.append(name)
        while self._nonland_total(counts) < 62:
            if not self._add_ranked_candidate(counts, ranked_nonlands, request.format, list(commander_identity), request.budget, excluded, commander_name=commander):
                break

        self._add_lands_from_packages(counts, list(commander_identity), LAND_TARGET_COMMANDER, package.land_package if package else [], request.format)
        while self._total_cards(counts) > COMMANDER_DECK_SIZE:
            self._trim_excess_land_or_spell(counts, list(commander_identity))
        while self._total_cards(counts) < COMMANDER_DECK_SIZE:
            self._add_basic_land(counts, list(commander_identity))
        return self._counts_to_refs(counts)

    def _build_title(self, request: GenerateDeckRequest, archetype: ArchetypeRecord, commander: str | None) -> str:
        modifiers = [tag.title() for tag in request.theme_tags[:1] + request.playstyle_tags[:1] if tag]
        anchor = commander or archetype.name
        return f"{' '.join(modifiers + [anchor, archetype.name if commander and archetype.name != commander else '']).strip()}".strip()

    def _build_explanation(
        self,
        archetype: ArchetypeRecord,
        request: GenerateDeckRequest,
        colors: list[str],
        mainboard: list[CardRef],
        sideboard: list[CardRef],
        warnings: list[str],
        commander_reason: str | None,
        outcome: _RetrievalOutcome,
    ) -> list[str]:
        total_lands = sum(ref.quantity for ref in mainboard if (card := self.repository.get_card(ref.name)) and "Land" in card.type_line)
        role_summary = self._build_role_summary(mainboard)
        provenance_blurb = {
            "corpus": f"Started from the {archetype.name} shell, backed by {outcome.evidence_count} corpus deck(s) of supporting evidence.",
            "fallback": f"No matching corpus shell was found — the deck was assembled from the legal card pool using deterministic role and color filters (low confidence: {outcome.confidence:.2f}).",
            "hybrid": f"Started from the {archetype.name} shell but most slots were filled by deterministic fallbacks (mixed confidence: {outcome.confidence:.2f}).",
        }[outcome.source_type]
        notes = [
            provenance_blurb,
            f"The final list carries {total_lands} lands and was assembled around retrieved packages rather than independent card picks.",
            f"Role balance snapshot: {', '.join(f'{item.role} {item.total_cards}' for item in role_summary[:4])}.",
        ]
        if request.format == "commander" and commander_reason:
            notes.append(commander_reason)
        if sideboard:
            notes.append("The sideboard leans on retrieved matchup packages and fallback interaction packages.")
        if request.budget is not None:
            notes.append("Budget sensitivity was applied while choosing retrieval candidates and fallbacks.")
        if warnings:
            notes.append(f"Open issues still worth reviewing: {'; '.join(warnings[:3])}")
        return notes

    def _build_sections(
        self,
        archetype: ArchetypeRecord,
        request: GenerateDeckRequest,
        mainboard: list[CardRef],
        sideboard: list[CardRef],
        commander: str | None,
        warnings: list[str],
        commander_reason: str | None,
        outcome: _RetrievalOutcome,
    ) -> list[DeckSectionSummary]:
        retrieval_summary = {
            "corpus": f"Backed by {outcome.evidence_count} corpus deck(s); confidence {outcome.confidence:.2f}.",
            "fallback": f"No matching corpus shell — assembled from card pool. Confidence {outcome.confidence:.2f}.",
            "hybrid": f"Hybrid of corpus shell and card-pool fallback. Confidence {outcome.confidence:.2f}.",
        }[outcome.source_type]
        sections = [
            DeckSectionSummary(
                title="Game Plan",
                summary=archetype.strategy,
                bullets=[
                    f"Primary colors: {' / '.join(request.colors or archetype.colors) or 'open'}",
                    f"Retrieved shell: {archetype.name}" if outcome.source_type != "fallback" else "No corpus shell matched the request.",
                    retrieval_summary,
                ],
            ),
        ]
        if outcome.source_type != "fallback":
            sections.append(
                DeckSectionSummary(
                    title="Retrieved Packages",
                    summary="Core, flex, land, and support packages shaped the final list.",
                    bullets=[
                        f"Core package count: {len(archetype.metadata.core_cards)}",
                        f"Flex package count: {len(archetype.metadata.flex_cards)}",
                        f"Land package count: {len(archetype.metadata.land_packages)}",
                        f"Commander package: {'yes' if archetype.metadata.commander_package else 'no'}",
                    ],
                )
            )
        if commander_reason:
            sections.append(DeckSectionSummary(title="Commander Choice", summary=commander_reason, bullets=[f"Commander: {commander or 'n/a'}"]))
        sections.append(
            DeckSectionSummary(
                title="Configuration",
                summary="Mana base and support package were adjusted after retrieval.",
                bullets=[
                    f"Mainboard cards: {sum(ref.quantity for ref in mainboard)}",
                    f"Sideboard cards: {sum(ref.quantity for ref in sideboard)}",
                    f"Commander: {commander or 'n/a'}",
                ],
            )
        )
        if warnings:
            sections.append(DeckSectionSummary(title="Watchouts", summary="A few structural risks remain worth testing in games.", bullets=warnings[:4]))
        return sections

    def _build_mechanics(self, mainboard: list[CardRef], commander: str | None) -> list[DeckMechanic]:
        tag_to_cards: defaultdict[str, list[str]] = defaultdict(list)
        for ref in mainboard:
            card = self.repository.get_card(ref.name)
            if not card or "Land" in card.type_line:
                continue
            for tag in card.tags:
                if tag in {"interaction", "draw", "ramp", "prowess", "tokens", "lifegain", "graveyard", "tribal", "spells"}:
                    tag_to_cards[tag].append(card.name)
        mechanics: list[DeckMechanic] = []
        for tag, cards in sorted(tag_to_cards.items(), key=lambda item: len(item[1]), reverse=True)[:4]:
            summary = f"The deck uses {tag} as a recurring axis rather than a one-off inclusion."
            if commander:
                summary = f"The commander shell reinforces {tag} through retrieved support packages and signature cards."
            mechanics.append(DeckMechanic(label=tag.title(), summary=summary, cards=cards[:5]))
        return mechanics

    def _build_role_summary(self, refs: list[CardRef]) -> list[DeckRoleSummary]:
        counts: defaultdict[str, int] = defaultdict(int)
        key_cards: defaultdict[str, list[str]] = defaultdict(list)
        for ref in refs:
            card = self.repository.get_card(ref.name)
            if not card:
                continue
            role = self._primary_role(card)
            counts[role] += ref.quantity
            if card.name not in key_cards[role] and len(key_cards[role]) < 4 and "Land" not in card.type_line:
                key_cards[role].append(card.name)
        ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        return [DeckRoleSummary(role=role, total_cards=total, key_cards=key_cards[role]) for role, total in ordered]

    def _build_mana_curve(self, refs: list[CardRef]) -> list[ManaCurvePoint]:
        buckets = Counter[int]()
        for ref in refs:
            card = self.repository.get_card(ref.name)
            if not card or "Land" in card.type_line:
                continue
            buckets[min(6, int(card.mana_value))] += ref.quantity
        return [ManaCurvePoint(mana_value=value, card_count=buckets[value]) for value in range(0, 7)]

    def _build_card_notes(self, refs: list[CardRef]) -> list[DeckCardExplanation]:
        notes: list[DeckCardExplanation] = []
        for ref in refs:
            card = self.repository.get_card(ref.name)
            if not card or "Basic Land" in card.type_line:
                continue
            role = self._primary_role(card)
            notes.append(
                DeckCardExplanation(
                    name=card.name,
                    role=role,
                    reason=f"{card.name} is included as a {role} from the retrieved shell or package set.",
                )
            )
            if len(notes) >= 15:
                break
        return notes

    @staticmethod
    def _canonicalize_tag(tag: str) -> str:
        normalized = tag.strip().lower()
        return CANONICAL_TAGS.get(normalized, normalized)

    def _rank_cards(
        self,
        format_name: str,
        colors: list[str],
        requested_tags: list[str],
        budget: float | None,
        excluded_cards: set[str],
    ) -> list[str]:
        preferred_tags = set(requested_tags)
        expanded_tags: set[str] = set(preferred_tags)
        for tag in preferred_tags:
            expanded_tags.update(THEME_TO_TAGS.get(tag, {tag}))
        scored: list[tuple[float, str]] = []
        for card in self.repository.all_cards():
            if card.name.lower() in excluded_cards:
                continue
            if not self._is_card_legal_record(card, format_name):
                continue
            if not self._matches_color_request(card, colors):
                continue
            if budget is not None and not self._fits_budget_request(card, budget):
                continue
            score = len(expanded_tags & set(card.tags)) * 9
            score += 2 if "Land" in card.type_line else max(0, 5 - card.mana_value)
            if "interaction" in card.tags:
                score += 3
            if "draw" in card.tags or "ramp" in card.tags:
                score += 2
            scored.append((score, card.name))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [name for _, name in scored]

    def _is_card_legal_record(self, card: CardRecord, format_name: str) -> bool:
        return card.legalities.get(format_name, "not_legal") in {"legal", "restricted"}

    def _check_include_cards(self, request: GenerateDeckRequest) -> list[str]:
        warnings: list[str] = []
        unresolved: list[str] = []
        over_budget: list[str] = []
        for name in request.include_cards:
            card = self.repository.get_card(name)
            if not card:
                unresolved.append(name)
            elif request.budget is not None and not self._fits_budget_request(card, request.budget):
                over_budget.append(card.name)
        if unresolved:
            warnings.append(f"Could not find card(s) to include: {', '.join(unresolved)}. Check spelling.")
        if over_budget:
            warnings.append(f"Forced card(s) exceed requested budget: {', '.join(over_budget)}.")
        return warnings

    @staticmethod
    def _copy_limit(card: CardRecord, format_name: str) -> int | None:
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

    def _ordered_commander_identity(self, commander_name: str | None, fallback_colors: list[str]) -> list[str]:
        if not commander_name:
            return fallback_colors
        commander = self.repository.get_card(commander_name)
        if not commander:
            return fallback_colors
        return list(commander.color_identity or commander.colors or fallback_colors)

    @staticmethod
    def _matches_color_request(card: CardRecord, requested_colors: list[str]) -> bool:
        if not requested_colors:
            return True
        identity = set(card.color_identity or card.colors)
        requested = set(requested_colors)
        wants_colorless = "C" in requested
        requested_colored = requested - {"C"}
        if wants_colorless and not requested_colored:
            return not identity
        if wants_colorless and requested_colored:
            return not identity or identity.issubset(requested_colored)
        return not identity or identity.issubset(requested)

    @staticmethod
    def _fits_budget_request(card: CardRecord, budget: float | None) -> bool:
        if budget is None or card.price_usd is None:
            return True
        per_card_cap = max(0.50, min(budget / 20.0, budget * 0.12))
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

    def _target_land_count(self, archetype: ArchetypeRecord, requested_tags: list[str]) -> int:
        if {"aggro", "tempo", "spells"} & set(requested_tags):
            return LAND_TARGET_AGGRO
        if {"control", "midrange", "combo"} & set(requested_tags):
            return LAND_TARGET_DEFAULT
        if "ramp" in requested_tags:
            return LAND_TARGET_RAMP
        curve = {int(item["mana_value"]): float(item["weight"]) for item in archetype.metadata.mana_curve_profile if "mana_value" in item}
        high_end = curve.get(4, 0) + curve.get(5, 0) + curve.get(6, 0)
        return LAND_TARGET_DEFAULT if high_end > 10 else LAND_TARGET_DEFAULT - 1

    @staticmethod
    def _profile_to_commander_package(profile) -> CommanderPackageSummary:
        return CommanderPackageSummary(
            commander_name=profile.card.name,
            popularity=profile.popularity,
            support_depth=profile.support_depth,
            average_lands=profile.average_lands,
            average_ramp=profile.average_ramp,
            average_draw=profile.average_draw,
            average_interaction=profile.average_interaction,
            signature_cards=profile.signature_cards,
            synergy_packages=profile.synergy_packages,
            ramp_package=profile.ramp_package,
            draw_package=profile.draw_package,
            interaction_package=profile.interaction_package,
            land_package=profile.land_package,
        )

    def _add_lands_from_packages(self, counts: Counter[str], colors: list[str], target_lands: int, packages: list[ArchetypePackage], format_name: str = "modern") -> None:
        # Color-identity-aware: a sliver-shaped land package will not leak
        # off-color basics into a narrow-color deck. This filter applies to
        # ALL formats when the caller passed an explicit color list — a UR
        # dual land in a mono-R modern deck is technically legal but is never
        # what the user asked for (the U source is dead weight).
        identity = {color for color in colors if color and color != "C"}
        for package in packages:
            if self._land_total(counts) >= target_lands:
                break
            card = self.repository.get_card(package.name)
            if not card or "Land" not in card.type_line:
                continue
            if identity and not self.repository.fits_color_identity(card, identity):
                continue
            limit = self._copy_limit(card, format_name)
            if limit is not None and counts[card.name] >= limit:
                continue
            desired = max(1, int(round(package.average_quantity or 1)))
            if limit is not None:
                desired = min(desired, limit - counts[card.name])
            counts[card.name] += desired
        self._add_lands(counts, colors, target_lands)

    def _add_lands(self, counts: Counter[str], colors: list[str], target_lands: int) -> None:
        basics = self._basic_lands_for_colors(colors) or ["Mountain"]
        while self._land_total(counts) < target_lands:
            land_name = basics[self._land_total(counts) % len(basics)]
            counts[land_name] += 1

    def _add_basic_land(self, counts: Counter[str], colors: list[str]) -> None:
        basics = self._basic_lands_for_colors(colors) or ["Mountain"]
        counts[basics[self._total_cards(counts) % len(basics)]] += 1

    def _basic_lands_for_colors(self, colors: list[str]) -> list[str]:
        """Return basic lands for a set of colors. Order is deterministic.

        For an empty/colorless `colors` list, returns Wastes if available so
        callers do not silently get Plains/Island/Swamp/Mountain/Forest mixed
        into a colorless deck.
        """
        mapping = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
        seen: list[str] = []
        for color in sorted({c for c in colors if c in mapping}):
            land = mapping[color]
            if self.repository.get_card(land):
                seen.append(land)
        if seen:
            return seen
        wastes = self.repository.get_card("Wastes")
        return ["Wastes"] if wastes else ["Mountain"]

    def _add_package_cards(
        self,
        counts: Counter[str],
        packages: list[ArchetypePackage],
        *,
        target: int,
        format_name: str,
        colors: list[str],
        excluded: set[str],
    ) -> None:
        # Count only cards added by this specific call so targets are independent across roles.
        added = 0
        for package in packages:
            if added >= target:
                break
            card = self.repository.get_card(package.name)
            if not card or package.name.lower() in excluded:
                continue
            if not self._is_card_legal_record(card, format_name) or not self._matches_color_request(card, colors):
                continue
            if counts[card.name] >= (self._copy_limit(card, format_name) or 99):
                continue
            counts[card.name] += 1
            added += 1

    def _add_ranked_candidate(
        self,
        counts: Counter[str],
        ranked_candidates: list[str],
        format_name: str,
        colors: list[str],
        budget: float | None,
        excluded_cards: set[str],
        main_counts: Counter[str] | None = None,
        commander_name: str | None = None,
        allow_lands: bool = False,
    ) -> bool:
        main_counts = main_counts or Counter()
        for candidate_name in ranked_candidates:
            card = self.repository.get_card(candidate_name)
            if not card or candidate_name.lower() in excluded_cards:
                continue
            if not allow_lands and "Land" in card.type_line:
                continue
            if commander_name and card.name == commander_name:
                continue
            if not self._is_card_legal_record(card, format_name) or not self._matches_color_request(card, colors):
                continue
            if budget is not None and not self._fits_budget_request(card, budget):
                continue
            if format_name == "commander" and not self.repository.fits_color_identity(card, set(colors)):
                continue
            limit = self._copy_limit(card, format_name)
            if limit is not None and counts[card.name] + main_counts[card.name] >= limit:
                continue
            counts[card.name] += 1
            return True
        return False

    def _best_card_pool_commander(self, colors: list[str], requested_tags: list[str]) -> tuple[str | None, str | None]:
        requested_color_set = set(colors)
        expanded_tags = set(requested_tags)
        for tag in requested_tags:
            expanded_tags.update(THEME_TO_TAGS.get(tag, {tag}))
        best_name: str | None = None
        best_score = float("-inf")
        for card in self.repository.all_cards():
            if not self.repository.is_legal_commander(card):
                continue
            identity = set(card.color_identity or card.colors)
            if requested_color_set and (not identity or not identity.issubset(requested_color_set)):
                continue
            tag_score = len(expanded_tags & set(card.tags)) * 12
            color_score = len(identity) * 2
            cost_score = max(0, 6 - card.mana_value)
            score = tag_score + color_score + cost_score
            if score > best_score:
                best_score = score
                best_name = card.name
        if best_name is None:
            return None, None
        return best_name, f"Selected {best_name} from the full commander card pool because it fit the requested colors and had the deepest matching support pool."

    def _decrement_least_important(self, counts: Counter[str], format_name: str) -> None:
        removable: list[tuple[float, str]] = []
        for name, quantity in counts.items():
            if quantity <= 0:
                continue
            card = self.repository.get_card(name)
            if not card or "Basic Land" in card.type_line:
                continue
            weight = 100.0 if "Land" in card.type_line else 10.0 + card.mana_value
            if "interaction" in card.tags:
                weight = 35.0
            elif "creature" in card.tags:
                weight = 20.0
            removable.append((weight, name))
        if removable:
            _, name = sorted(removable, reverse=True)[0]
            counts[name] -= 1
            if counts[name] <= 0:
                del counts[name]

    def _trim_excess_land_or_spell(self, counts: Counter[str], colors: list[str]) -> None:
        for basic_land in reversed(self._basic_lands_for_colors(colors)):
            if counts[basic_land] > 0:
                counts[basic_land] -= 1
                if counts[basic_land] <= 0:
                    del counts[basic_land]
                return
        self._decrement_least_important(counts, "modern")

    def _add_best_remaining(self, counts: Counter[str], ranked_candidates: list[str], format_name: str) -> None:
        for candidate_name in ranked_candidates:
            card = self.repository.get_card(candidate_name)
            if not card:
                continue
            limit = self._copy_limit(card, format_name)
            if limit is not None and counts[card.name] >= limit:
                continue
            counts[card.name] += 1
            return
        self._add_basic_land(counts, ["R"])

    def _primary_role(self, card: CardRecord | None) -> str:
        if not card:
            return "flex slot"
        for tag in card.tags:
            if tag in ROLE_MAP:
                return ROLE_MAP[tag]
        if "Land" in card.type_line:
            return "mana base"
        if "Creature" in card.type_line:
            return "threat"
        return "flex slot"

    @staticmethod
    def _counts_to_refs(counts: Counter[str]) -> list[CardRef]:
        return [CardRef(name=name, quantity=quantity) for name, quantity in sorted(counts.items()) if quantity > 0]

    @staticmethod
    def _total_cards(counts: Counter[str]) -> int:
        return sum(counts.values())

    def _land_total(self, counts: Counter[str]) -> int:
        total = 0
        for name, quantity in counts.items():
            card = self.repository.get_card(name)
            if card and "Land" in card.type_line:
                total += quantity
        return total

    def _nonland_total(self, counts: Counter[str]) -> int:
        return self._total_cards(counts) - self._land_total(counts)

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
        lines = [deck.title, ""]
        if deck.commander:
            lines.append(f"1 {deck.commander}")
            lines.append("")
        lines.extend(f"{card.quantity} {card.name}" for card in deck.mainboard)
        if deck.sideboard:
            lines.append("")
            lines.append("Sideboard")
            lines.extend(f"{card.quantity} {card.name}" for card in deck.sideboard)
        return "\n".join(lines)
