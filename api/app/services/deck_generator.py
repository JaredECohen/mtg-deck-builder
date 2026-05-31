from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

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
from app.services.builtin_archetypes import (
    BuiltinArchetype,
    blend_archetypes,
    detect_builtin_archetypes,
)
from app.services.card_repository import CardRepository
from app.services.deck_validator import DeckValidator
from app.services.llm_service import (
    RefinementIntent,
    compose_from_scratch,
    interpret_generate_prompt,
    interpret_refinement,
    refine_blend,
    refine_compose,
)


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

        # Built-in archetype seeds: when the brief names known shell(s) that
        # the tournament corpus doesn't cover (Burn, Tron, Yawgmoth, ...), we
        # inject canonical anchor cards into include_cards and merge the
        # archetype's tags. If the brief matches multiple archetypes (e.g.
        # "burn + lifegain", "boros burn into heliod combo"), they are
        # blended into a synthetic hybrid before being applied. See
        # app/services/builtin_archetypes.py for the seed map.
        matches = detect_builtin_archetypes(request.prompt, request.format)
        builtin = blend_archetypes(matches, request.format) if matches else None

        # Compose-from-scratch fallback: when the brief has substance but no
        # builtin matched, ask Claude to compose ~30 anchor cards instead of
        # letting the corpus pick a near-miss shell. Synthesizes a transient
        # BuiltinArchetype so the rest of the pipeline doesn't change.
        if builtin is None and request.prompt and request.prompt.strip():
            composed = compose_from_scratch(
                format_name=request.format,
                colors=list(request.colors),
                playstyle_tags=list(request.playstyle_tags),
                theme_tags=list(request.theme_tags),
                budget=request.budget,
                user_brief=request.prompt,
            )
            if composed is not None:
                # Second-pass refinement: ask Claude to tighten the
                # compose result (cut redundancies, add bridge cards,
                # balance the curve). On LLM failure we keep the raw
                # compose output.
                refined = refine_compose(
                    composed=composed,
                    format_name=request.format,
                    colors=list(request.colors),
                    budget=request.budget,
                    user_brief=request.prompt,
                )
                final_composed = refined if refined is not None else composed
                colors_tuple = tuple(request.colors) if request.colors else ()
                builtin = BuiltinArchetype(
                    id="composed-" + str(abs(hash(request.prompt)) % 10_000_000),
                    display_name=final_composed["archetype_label"] or "Composed",
                    keywords=(),
                    formats=(request.format,),
                    colors=colors_tuple,
                    playstyle_tags=tuple(request.playstyle_tags),
                    theme_tags=tuple(request.theme_tags),
                    anchor_cards=tuple((n, q) for n, q in final_composed["anchor_cards"]),
                    strategy=final_composed["strategy"],
                )

        # If 2+ archetypes blended, ask the LLM to curate a more coherent
        # anchor list (cut redundancies, add bridge cards, balance the curve).
        # Falls through to the deterministic blend on no key or failure.
        if builtin is not None and len(matches) >= 2:
            llm_blend = refine_blend(
                matched_archetypes=[
                    {"display_name": m.display_name, "anchor_cards": list(m.anchor_cards)}
                    for m in matches[:3]
                ],
                format_name=request.format,
                colors=request.colors or list(builtin.colors),
                budget=request.budget,
                user_brief=request.prompt,
            )
            if llm_blend is not None and llm_blend.get("anchor_cards"):
                builtin = BuiltinArchetype(
                    id=builtin.id + "-llm",
                    display_name=builtin.display_name,
                    keywords=builtin.keywords,
                    formats=builtin.formats,
                    colors=builtin.colors,
                    playstyle_tags=builtin.playstyle_tags,
                    theme_tags=builtin.theme_tags,
                    anchor_cards=tuple((n, q) for n, q in llm_blend["anchor_cards"]),
                    strategy=llm_blend.get("blended_strategy") or builtin.strategy,
                )

        if builtin is not None:
            # Push anchors through seed_cards (preserves quantity) and into
            # include_cards (forces presence). Without seed_cards the include
            # path clamps to ~2 copies, so 4x anchors never reach 4x.
            anchor_seeds: list[CardRef] = []
            anchor_names: list[str] = []
            existing_seed_names = {ref.name.lower() for ref in request.seed_cards}
            for name, qty in builtin.anchor_cards:
                if qty <= 0:
                    continue
                if not self.repository.get_card(name):
                    continue
                anchor_names.append(name)
                if name.lower() not in existing_seed_names:
                    anchor_seeds.append(CardRef(name=name, quantity=qty))
            request = request.model_copy(update={
                "colors": request.colors or list(builtin.colors),
                "playstyle_tags": list(dict.fromkeys(list(request.playstyle_tags) + list(builtin.playstyle_tags))),
                "theme_tags": list(dict.fromkeys(list(request.theme_tags) + list(builtin.theme_tags))),
                "include_cards": list(dict.fromkeys(list(request.include_cards) + anchor_names)),
                "seed_cards": list(request.seed_cards) + anchor_seeds,
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
            outcome = self._retrieve_for_constructed(request, builtin=builtin)
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

        # Honest confidence: replace the old "did we find a shell" signal with
        # a composite of (a) intent-match — did the brief's archetype match
        # what we built? — and (b) anchor coverage — does the mainboard
        # actually contain the canonical anchors for the labeled archetype?
        # Previously a W Lifegain Payoff result for "build a burn deck"
        # claimed 95% because the corpus shell was clean; now it would
        # correctly fall into the 0.30 range.
        confidence = self._compute_honest_confidence(
            outcome=outcome,
            builtin=builtin,
            matches=matches,
            mainboard=mainboard,
            request=request,
        )
        # Queue sim validation for blends (2+ archetypes merged) so the
        # frontend can show a "validated by simulator" badge once the
        # optimizer finishes. Best-effort — any failure is swallowed so the
        # generation response isn't blocked by optimizer queue issues.
        sim_job_id: str | None = None
        if len(matches) >= 2 and request.format != "commander":
            try:
                from app.services.optimizer_service import OptimizerJobRequest, submit_optimize_job
                anchor_names = [name for name, _ in builtin.anchor_cards if self.repository.get_card(name)] if builtin else []
                opt_request = OptimizerJobRequest(
                    format=request.format,
                    colors=list(request.colors),
                    budget_usd=request.budget,
                    include_cards=anchor_names[:16],  # cap so the optimizer can move
                    rounds=4,  # short loop; this is validation, not full search
                    proposals_per_round=2,
                    sim_runs_per_eval=80,
                )
                opt_response = submit_optimize_job(opt_request, repository=self.repository)
                sim_job_id = opt_response.job_id
            except Exception:
                logger.debug("sim validation queue failed (non-blocking)", exc_info=True)

        provenance = DeckProvenance(
            source_type=outcome.source_type,
            confidence=round(confidence, 3),
            evidence_count=outcome.evidence_count,
            retrieved_from=outcome.retrieved_from,
            fallback_used=outcome.fallback_used,
            notes=outcome.notes,
            sim_validation_job_id=sim_job_id,
        )

        # Final hard legality gate for commander format. The validator already
        # ran but if it surfaced color-identity errors we treat those as a
        # generation bug, not a deck-quality warning, and refuse to lie about
        # legality even if a basic land had to be substituted in.
        if request.format == "commander" and legality_actions:
            warnings.insert(0, "Generator substituted off-color cards with basic lands to honor commander color identity.")

        # If a built-in archetype seed was matched, prefer its display name
        # and a synthesized strategy line so the deck doesn't show the
        # corpus's nearest-neighbor archetype ("Izzet Prowess") for a
        # request that was clearly something else ("burn").
        if builtin is not None:
            # Commander format with a chosen commander reads as
            # "{commander} — {archetype}" so the table can scan who's at the
            # helm before what the deck is doing.
            if request.format == "commander" and commander:
                title = f"{commander} — {builtin.display_name}"
            else:
                # Avoid stuttering when the display_name already includes the
                # format word ("Legacy Reanimator" → "Legacy Legacy Reanimator").
                format_word = request.format.title()
                if builtin.display_name.lower().startswith(request.format.lower()):
                    title = builtin.display_name
                else:
                    title = f"{format_word} {builtin.display_name}"
            strategy_summary = (
                builtin.strategy
                or f"Built from a {builtin.display_name} seed: canonical anchor cards in this archetype, "
                f"with the rest filled from the {request.format} card pool."
            )
        else:
            title = self._build_title(request, base, commander)
            strategy_summary = base.strategy

        return DeckResponse(
            format=request.format,
            title=title,
            colors=colors,
            commander=commander,
            strategy_summary=strategy_summary,
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

    # Modern-legal fetchlands grouped by what they search for. Used by the
    # mana_base template materializer to pick correct fetches for the colors.
    _FETCHES_BY_COLOR_PAIR: dict[tuple[str, str], str] = {
        ("R", "G"): "Wooded Foothills",
        ("R", "W"): "Arid Mesa",
        ("R", "U"): "Scalding Tarn",
        ("R", "B"): "Bloodstained Mire",
        ("U", "G"): "Misty Rainforest",
        ("U", "W"): "Flooded Strand",
        ("U", "B"): "Polluted Delta",
        ("B", "G"): "Verdant Catacombs",
        ("B", "W"): "Marsh Flats",
        ("G", "W"): "Windswept Heath",
    }
    _SHOCKS_BY_COLOR_PAIR: dict[tuple[str, str], str] = {
        ("R", "W"): "Sacred Foundry",
        ("U", "R"): "Steam Vents",
        ("U", "W"): "Hallowed Fountain",
        ("B", "G"): "Overgrown Tomb",
        ("R", "G"): "Stomping Ground",
        ("G", "W"): "Temple Garden",
        ("B", "W"): "Godless Shrine",
        ("U", "B"): "Watery Grave",
        ("R", "B"): "Blood Crypt",
        ("U", "G"): "Breeding Pool",
    }

    def _materialize_mana_base(
        self,
        template: "ManaBaseTemplate",
        colors: list[str],
    ) -> list[ArchetypePackage]:
        """Turn a ManaBaseTemplate + color request into concrete
        ArchetypePackage entries for utility lands, shocks, fetches, basics.

        The fractions (shocks_ratio, fetches_ratio) are applied to total
        land slots minus utility + basics_min, so a "20 lands, 25% shocks,
        50% fetches" template on a 2-color deck produces:
          • utility lands as declared
          • ceil((20 - util - basics_min) * 0.25) shocks split across colors
          • ceil((20 - util - basics_min) * 0.50) fetches
          • basics filling the remainder, never below basics_min
        """
        # Normalize colors (drop C; uppercase).
        colors_clean = [c.upper() for c in colors if c.upper() in {"W", "U", "B", "R", "G"}]

        packages: list[ArchetypePackage] = []
        used = 0
        # 1. Utility lands at fixed quantities.
        for name, qty in template.utility_lands:
            if qty > 0:
                packages.append(ArchetypePackage(name=name, average_quantity=float(qty), inclusion_rate=1.0))
                used += qty

        remaining = max(0, template.total_lands - used - template.basics_min)

        # 2. Shocks split across color pairs present.
        if template.shocks_ratio > 0 and len(colors_clean) >= 2:
            shock_total = max(0, int(round(remaining * template.shocks_ratio)))
            pairs = self._color_pairs(colors_clean)
            picked: list[str] = []
            for pair in pairs:
                land = self._SHOCKS_BY_COLOR_PAIR.get(pair) or self._SHOCKS_BY_COLOR_PAIR.get((pair[1], pair[0]))
                if land:
                    picked.append(land)
            per_pair = max(1, shock_total // len(picked)) if picked else 0
            for land in picked[: shock_total // max(1, per_pair) + 1]:
                qty = min(per_pair, shock_total)
                if qty <= 0:
                    break
                packages.append(ArchetypePackage(name=land, average_quantity=float(qty), inclusion_rate=1.0))
                shock_total -= qty
                used += qty
                remaining -= qty
                if shock_total <= 0:
                    break

        # 3. Fetches.
        if template.fetches_ratio > 0 and len(colors_clean) >= 2:
            fetch_total = max(0, int(round(remaining * template.fetches_ratio / max(1.0 - template.shocks_ratio, 0.01))))
            pairs = self._color_pairs(colors_clean)
            picked = []
            for pair in pairs:
                land = self._FETCHES_BY_COLOR_PAIR.get(pair) or self._FETCHES_BY_COLOR_PAIR.get((pair[1], pair[0]))
                if land:
                    picked.append(land)
            per_pair = max(1, fetch_total // len(picked)) if picked else 0
            for land in picked[: fetch_total // max(1, per_pair) + 1]:
                qty = min(per_pair, fetch_total)
                if qty <= 0:
                    break
                packages.append(ArchetypePackage(name=land, average_quantity=float(qty), inclusion_rate=1.0))
                fetch_total -= qty
                used += qty
                remaining -= qty
                if fetch_total <= 0:
                    break

        # 4. Basics for the rest, distributed across colors.
        basics_target = max(template.basics_min, template.total_lands - used)
        if basics_target > 0:
            basics = self._basic_lands_for_colors(colors_clean or ["C"])
            if not basics:
                basics = ["Wastes"]
            per_color = max(1, basics_target // len(basics))
            placed = 0
            for i, basic in enumerate(basics):
                qty = basics_target - placed if i == len(basics) - 1 else per_color
                qty = max(0, qty)
                if qty <= 0:
                    break
                packages.append(ArchetypePackage(name=basic, average_quantity=float(qty), inclusion_rate=1.0))
                placed += qty

        return packages

    @staticmethod
    def _color_pairs(colors: list[str]) -> list[tuple[str, str]]:
        """Return all unique 2-color pairs from the given colors list."""
        out: list[tuple[str, str]] = []
        for i in range(len(colors)):
            for j in range(i + 1, len(colors)):
                out.append((colors[i], colors[j]))
        return out

    def _synthesize_outcome_from_builtin(
        self, builtin: BuiltinArchetype, request: GenerateDeckRequest
    ) -> _RetrievalOutcome:
        """Build a retrieval outcome from a builtin archetype seed.

        Used when the requested format has no corpus archetypes at all (e.g.
        Pioneer in our current data) but the user's brief matched a known
        builtin shell. Synthesizes an ArchetypeRecord so downstream pipeline
        steps (mainboard fill, strategy summary, sections) all run normally.
        """
        # If the archetype carries a mana_base template, strip any hand-
        # listed lands from anchor_cards — they'd otherwise compete with
        # the template's recipe. The template-driven materialization runs
        # later in _materialize_mana_base via outcome.notes plumbing.
        def _is_land(name: str) -> bool:
            card = self.repository.get_card(name)
            return bool(card and "Land" in card.type_line)

        mainboard_anchors = list(builtin.anchor_cards)
        if builtin.mana_base is not None:
            mainboard_anchors = [
                (name, qty) for name, qty in mainboard_anchors
                if not _is_land(name)
            ]
        mainboard = [
            CardRef(name=name, quantity=qty)
            for name, qty in mainboard_anchors
            if qty > 0 and self.repository.get_card(name)
        ]
        sideboard = [
            CardRef(name=name, quantity=qty)
            for name, qty in builtin.sideboard_anchors
            if qty > 0 and self.repository.get_card(name)
        ]
        # Mana-base template → concrete ArchetypePackage list (utility,
        # shocks, fetches, basics). The existing _add_lands_from_packages
        # path consumes this transparently.
        land_packages: list[ArchetypePackage] = []
        if builtin.mana_base is not None:
            colors_for_mb = request.colors or list(builtin.colors)
            land_packages = self._materialize_mana_base(builtin.mana_base, colors_for_mb)
        archetype_metadata = ArchetypeMetadata(land_packages=land_packages)
        base = ArchetypeRecord(
            id=builtin.id,
            name=builtin.display_name,
            format=request.format,
            colors=list(builtin.colors),
            tags=list(builtin.playstyle_tags + builtin.theme_tags),
            strategy=(
                builtin.strategy
                or f"Canonical {builtin.display_name} shell seeded from a built-in template."
            ),
            mainboard=mainboard,
            sideboard=sideboard,
            commander=None,
            source_count=0,
            avg_placement=None,
            metadata=archetype_metadata,
        )
        return _RetrievalOutcome(
            base=base,
            candidates=[base],
            source_type="builtin",
            confidence=0.7,
            evidence_count=0,
            retrieved_from=[builtin.display_name],
            fallback_used=True,
            notes=[
                f"Format '{request.format}' has no corpus archetypes; synthesized base from built-in {builtin.display_name} seed.",
            ],
        )

    def _retrieve_for_constructed(
        self,
        request: GenerateDeckRequest,
        builtin: BuiltinArchetype | None = None,
    ) -> _RetrievalOutcome:
        # If the user named (or blended) a known archetype, synthesize the
        # base from the builtin and skip corpus retrieval entirely. The
        # corpus is sparse and would otherwise pick an unrelated nearest-
        # neighbor shell whose flex cards leak into the mainboard (e.g.
        # picking "RU Spells Aggro" for a mono-red burn request and bleeding
        # in Slickshot Show-Off / Monstrous Rage).
        if builtin is not None:
            return self._synthesize_outcome_from_builtin(builtin, request)

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
            if builtin is not None:
                return self._synthesize_outcome_from_builtin(builtin, request)
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
        # When the base was synthesized from a builtin (source_count==0 and
        # no metadata.core_cards from the corpus), skip the corpus package
        # candidates. They're the source of leaks like Stormchaser's Talent
        # appearing in Modern Burn decks because the corpus picked a tagged
        # nearest-neighbor shell. The builtin's anchors are already seeded;
        # everything else is filled from the format card pool ranked by
        # color and theme match.
        from_builtin = archetype.source_count == 0 and not archetype.metadata.core_cards
        if from_builtin:
            ranked_candidates = self._rank_cards(request.format, colors, requested_tags, request.budget, excluded)
        else:
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
        # Builtin sideboard anchors: when the synthesized base carries a
        # curated sideboard (Burn → Smash to Smithereens, Roiling Vortex,
        # etc.), seed those first at their declared quantities. Eliminates
        # the "15 Mountains" / random role-pool grab bag for top archetypes.
        for ref in archetype.sideboard:
            card = self.repository.get_card(ref.name)
            if not card or not self._is_card_legal_record(card, request.format):
                continue
            if not self._matches_color_request(card, colors):
                continue
            counts[card.name] = min(ref.quantity, self._copy_limit(card, request.format) or ref.quantity)
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

        # Walk multiple role pools before giving up. Basic lands in a
        # sideboard are always wrong, so we never pad with them — better to
        # return a short sideboard than 15 Mountains.
        for role in ("interaction", "removal", "threat", "advantage", "ramp"):
            if self._total_cards(counts) >= SIDEBOARD_SIZE:
                break
            role_names = [
                item["name"]
                for item in self.repository.card_packages_by_role_theme(
                    format_name=request.format,
                    role=role,
                    theme_tags=requested_tags,
                    limit=20,
                )
            ]
            while self._total_cards(counts) < SIDEBOARD_SIZE:
                if not self._add_ranked_candidate(
                    counts, role_names, request.format, colors, request.budget, set(), main_counts
                ):
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

    # Canonical Commander baseline. Every commander deck should include
    # these unless explicitly excluded. The Sliver Queen output had ZERO of
    # these — no Sol Ring, no Command Tower, no Cultivate, no Rhystic Study.
    # That made the deck unplayable as a "real" commander build. Categorized
    # so the seeder can swap by color identity (artifacts always, color
    # cards only if the identity includes the color).
    _COMMANDER_BASELINE: list[tuple[str, frozenset[str]]] = [
        # (card_name, required_color_identity) — empty set = colorless / always
        ("Sol Ring", frozenset()),
        ("Arcane Signet", frozenset()),
        ("Command Tower", frozenset()),
        ("Skullclamp", frozenset()),
        ("Lightning Greaves", frozenset()),
        ("Swiftfoot Boots", frozenset()),
        # Ramp
        ("Cultivate", frozenset({"G"})),
        ("Kodama's Reach", frozenset({"G"})),
        ("Three Visits", frozenset({"G"})),
        ("Nature's Lore", frozenset({"G"})),
        ("Rampant Growth", frozenset({"G"})),
        ("Farseek", frozenset({"G"})),
        # Draw
        ("Rhystic Study", frozenset({"U"})),
        ("Mystic Remora", frozenset({"U"})),
        ("Sylvan Library", frozenset({"G"})),
        ("Esper Sentinel", frozenset({"W"})),
        # Spot removal
        ("Swords to Plowshares", frozenset({"W"})),
        ("Path to Exile", frozenset({"W"})),
        ("Generous Gift", frozenset({"W"})),
        ("Beast Within", frozenset({"G"})),
        ("Anguished Unmaking", frozenset({"W", "U", "B"})),
        ("Assassin's Trophy", frozenset({"B", "G"})),
        # Sweepers
        ("Wrath of God", frozenset({"W"})),
        ("Damnation", frozenset({"B"})),
        ("Blasphemous Act", frozenset({"R"})),
        ("Toxic Deluge", frozenset({"B"})),
        ("Farewell", frozenset({"W"})),
        # Treasure / fixing
        ("Sol Talisman", frozenset()),
        ("Mind Stone", frozenset()),
        ("Fellwar Stone", frozenset()),
        # Catch-all draw
        ("Cyclonic Rift", frozenset({"U"})),
    ]

    def _seed_commander_baseline(
        self,
        counts: Counter[str],
        commander_identity: set[str],
        excluded: set[str],
        format_name: str,
        budget: float | None,
    ) -> None:
        """Seed the canonical commander staples for the deck's color identity.
        Quantity=1 per card (singleton). Skips anything excluded or off-color.
        Run BEFORE archetype packages so these staples form the floor.
        """
        for name, requires in self._COMMANDER_BASELINE:
            if name.lower() in excluded:
                continue
            # Color identity check: card's identity must subset the commander's.
            # Empty `requires` means colorless / always eligible.
            if requires and not requires.issubset(commander_identity):
                continue
            card = self.repository.get_card(name)
            if not card or counts[card.name] > 0:
                continue
            if not self._is_card_legal_record(card, format_name):
                continue
            if not self.repository.fits_color_identity(card, commander_identity):
                continue
            if budget is not None and not self._fits_budget_request(card, budget):
                continue
            counts[card.name] = 1

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
        # Seed the canonical staples first so a Sliver Queen build never
        # ships without Sol Ring / Command Tower / Arcane Signet again.
        self._seed_commander_baseline(counts, commander_identity, excluded, request.format, request.budget)

        # Seed from the builtin's anchor cards (passed in via request.seed_cards)
        # BEFORE the corpus packages run. Previously this loop ran last and
        # only added if counts==0, which meant the corpus package's pet cards
        # for the commander beat the builtin's archetype-specific anchors —
        # so a "yawgmoth combo" request whose anchors include Wall of Roots,
        # Strangleroot Geist, Eldritch Evolution, Chord of Calling would get
        # an Aristocrats package instead. By seeding builtin anchors first,
        # the commander packages fill flex slots around them.
        # NOTE: Cards whose color identity isn't a subset of the commander's
        # are filtered here — that's a hard MTG rule, not a bug. A Modern
        # builtin like "Yawgmoth Combo" lists green support cards (Wall of
        # Roots, Strangleroot Geist, Chord of Calling) that are illegal
        # under a mono-B Yawgmoth, Thran Physician commander. The intersect
        # produces a mono-B Yawgmoth shell — the package path then fills
        # around the legal anchors.
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
                counts[card.name] = 1  # Commander is singleton.

        package = archetype.metadata.commander_package
        if package:
            self._add_package_cards(counts, package.ramp_package, target=COMMANDER_ROLE_TARGETS["ramp"], format_name=request.format, colors=list(commander_identity), excluded=excluded)
            self._add_package_cards(counts, package.draw_package, target=COMMANDER_ROLE_TARGETS["draw"], format_name=request.format, colors=list(commander_identity), excluded=excluded)
            self._add_package_cards(counts, package.interaction_package, target=COMMANDER_ROLE_TARGETS["interaction"], format_name=request.format, colors=list(commander_identity), excluded=excluded)
            self._add_package_cards(counts, package.synergy_packages, target=COMMANDER_ROLE_TARGETS["engine"], format_name=request.format, colors=list(commander_identity), excluded=excluded)
            self._add_package_cards(counts, package.signature_cards, target=COMMANDER_ROLE_TARGETS["payoff"], format_name=request.format, colors=list(commander_identity), excluded=excluded)

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
        # Commander branch: "{commander} — {short archetype label}". Strips
        # the commander name from the archetype label if the clusterer
        # embedded it (e.g. "Yawgmoth, Thran Physician Aristocrats Combo
        # Commander Shell"), and drops the redundant "Commander Shell"
        # suffix. Prevents the "Yawgmoth, Thran Physician Yawgmoth, Thran
        # Physician Commander Shell" doubling pattern.
        if commander:
            short_label = archetype.name
            for noise in (f"{commander} ", "Commander Shell", "Commander shell"):
                short_label = short_label.replace(noise, "").strip()
            short_label = re.sub(r"\s+", " ", short_label).strip(" -—")
            if not short_label or short_label == commander:
                return commander
            return f"{commander} — {short_label}"

        # Constructed: prefer the corpus archetype name; only prepend a
        # single playstyle/theme modifier if the corpus name doesn't
        # already start with one.
        archetype_name = archetype.name or ""
        modifiers = [tag.title() for tag in request.theme_tags[:1] + request.playstyle_tags[:1] if tag]
        modifier_words = {m.lower() for m in modifiers}
        starts_with_modifier = archetype_name.split(" ", 1)[0].lower() in modifier_words if archetype_name else False
        if starts_with_modifier or not modifiers:
            return archetype_name
        return f"{modifiers[0]} {archetype_name}".strip()

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
            "builtin": f"No corpus archetype was available for this format — assembled from the built-in {archetype.name} seed and filled from the legal card pool.",
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
            "builtin": f"Built from a curated {archetype.name} seed (no corpus archetype for this format). Confidence {outcome.confidence:.2f}.",
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
        config_bullets = [
            f"Mainboard cards: {sum(ref.quantity for ref in mainboard)}",
            f"Sideboard cards: {sum(ref.quantity for ref in sideboard)}",
        ]
        if request.format == "commander" and commander:
            config_bullets.append(f"Commander: {commander}")
        sections.append(
            DeckSectionSummary(
                title="Configuration",
                summary="Mana base and support package were adjusted after retrieval.",
                bullets=config_bullets,
            )
        )
        if warnings:
            sections.append(DeckSectionSummary(title="Watchouts", summary="A few structural risks remain worth testing in games.", bullets=warnings[:4]))
        return sections

    # Priority order for Key Mechanics tagging: most-specific tag wins so a
    # card with tags ["draw", "graveyard", "spells"] gets bucketed under
    # graveyard alone instead of appearing under all three. Stops the
    # "same 5 cards under every mechanic" duplication seen in earlier outputs.
    _MECHANIC_PRIORITY: tuple[str, ...] = (
        "tribal", "prowess", "graveyard", "lifegain", "tokens", "sacrifice",
        "ramp", "burn", "infect", "mill",
        "interaction", "draw", "spells",
    )
    _MECHANIC_KEY_TAGS: frozenset[str] = frozenset(_MECHANIC_PRIORITY)

    def _primary_mechanic_tag(self, card_tags: list[str]) -> str | None:
        """Pick at most one mechanic tag per card using the priority order.
        Returns None if the card has no mechanic-relevant tag."""
        tag_set = set(card_tags)
        for candidate in self._MECHANIC_PRIORITY:
            if candidate in tag_set:
                return candidate
        return None

    def _build_mechanics(self, mainboard: list[CardRef], commander: str | None) -> list[DeckMechanic]:
        tag_to_cards: defaultdict[str, list[str]] = defaultdict(list)
        for ref in mainboard:
            card = self.repository.get_card(ref.name)
            if not card or "Land" in card.type_line:
                continue
            primary = self._primary_mechanic_tag(card.tags)
            if primary is None:
                continue
            tag_to_cards[primary].append(card.name)
        mechanics: list[DeckMechanic] = []
        # Require at least 3 cards in a mechanic before surfacing it — a tag
        # with 1–2 hits is too sparse to call a "recurring axis."
        for tag, cards in sorted(tag_to_cards.items(), key=lambda item: len(item[1]), reverse=True):
            if len(cards) < 3:
                continue
            if len(mechanics) >= 4:
                break
            summary = f"{len(cards)} cards form a {tag} axis."
            if commander:
                summary = f"The commander shell reinforces {tag} through {len(cards)} support cards."
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

    # Set types that should never appear in a competitive deck regardless of
    # what Scryfall says about their legality. "funny" covers Un-sets and
    # Unfinity stickers (Happy Dead Squirrel, Sassy Gremlin Blood). The rest
    # are alt-art / Arena-only / collector printings.
    _BLOCKED_SET_TYPES = frozenset({"funny", "memorabilia", "alchemy"})

    def _compute_honest_confidence(
        self,
        *,
        outcome: _RetrievalOutcome,
        builtin: BuiltinArchetype | None,
        matches: list[BuiltinArchetype],
        mainboard: list[CardRef],
        request: GenerateDeckRequest,
    ) -> float:
        """Compute a confidence score that reflects whether the deck answers
        the brief, not just whether the engine found a shell.

        Mix three signals:
          1. Source bias: builtin ≫ blend ≫ corpus ≫ hybrid ≫ fallback.
          2. Anchor coverage: of the labeled archetype's anchor cards, what
             fraction made it into the mainboard?
          3. Intent match: did the brief contain a keyword that maps to the
             labeled archetype?

        Returns a value in [0.05, 0.98]. Capped below 1.0 because no deck is
        a perfect answer — there's always editorial judgement involved.
        """
        # Source bias — the floor.
        source_bias = {
            "builtin": 0.65,
            "corpus": 0.50,
            "hybrid": 0.35,
            "fallback": 0.20,
        }.get(outcome.source_type, 0.25)

        # Blend bonus: a 2-way blend that was LLM-curated reads as well-aimed
        # even though it's not a single corpus match.
        if len(matches) >= 2:
            source_bias = max(source_bias, 0.55)

        # Anchor coverage: when there's a builtin (single or blend), check
        # how many of its canonical anchors actually landed in the mainboard.
        anchor_coverage = 0.0
        if builtin is not None and builtin.anchor_cards:
            mainboard_names = {ref.name.lower() for ref in mainboard}
            anchors = [name for name, qty in builtin.anchor_cards if qty > 0]
            if anchors:
                present = sum(1 for name in anchors if name.lower() in mainboard_names)
                anchor_coverage = present / len(anchors)

        # Intent match: did the brief reference the labeled archetype at all?
        # Direct keyword hit = strong signal; meta-default route = soft signal.
        intent_match = 0.0
        if request.prompt and builtin is not None:
            prompt_lc = request.prompt.lower()
            for keyword in builtin.keywords:
                if keyword in prompt_lc:
                    intent_match = 1.0
                    break

        # Composite. Source bias is the floor; the coverage + intent terms
        # add headroom up to a cap. A high source_bias with poor coverage
        # still reads as moderately confident because the SHAPE was right.
        score = source_bias + 0.20 * anchor_coverage + 0.13 * intent_match
        return max(0.05, min(0.98, score))

    def _is_card_legal_record(self, card: CardRecord, format_name: str) -> bool:
        # Set-type gate: drops the joke / Arena-only / collector printings
        # backfilled by app/scripts/backfill_set_type.py. Cards from sets that
        # haven't been classified keep set_type=None and pass through, so
        # this is failure-open for normal printings.
        if card.set_type and card.set_type in self._BLOCKED_SET_TYPES:
            return False
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
        # If the archetype carries a mana_base template, its land_packages
        # sum to the canonical land count for this archetype. Respect that
        # instead of the tag-based heuristic — Burn wants 19, Tron wants 20,
        # Amulet wants 22. The heuristic returns the same value for every
        # aggro deck regardless of archetype.
        if archetype.metadata.land_packages:
            template_total = int(round(sum(
                float(pkg.average_quantity or 0) for pkg in archetype.metadata.land_packages
            )))
            if template_total > 0:
                return template_total
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
