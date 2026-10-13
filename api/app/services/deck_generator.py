from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import cached_property, lru_cache

logger = logging.getLogger(__name__)

from app.models import (
    ArchetypeMetadata,
    ArchetypePackage,
    ArchetypeRecord,
    CardRecord,
    CardRef,
    BudgetSubstitution,
    ColorSourcePoint,
    CommanderPackageSummary,
    DeckAlternative,
    DeckCardExplanation,
    DeckConstraints,
    DeckMechanic,
    DeckProvenance,
    DeckResponse,
    DroppedInclude,
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
from app.config import DATA_DIR
from app.rules import copy_limit, is_basic_land, is_land_card
from app.services.sideboard_classes import SIDEBOARD_CLASSES, classify
from app.services import brackets as bracket_rules
from app.services.deck_diff import diff_decks
from app.services.game_plan import build_game_plan
from app.services.grounding import card_mentions, ground_text
from app.services.builtin_archetypes import (
    BUILTIN_ARCHETYPES,
    BuiltinArchetype,
    blend_archetypes,
    detect_builtin_archetypes,
    prefer_color_compatible,
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
class _BuildTrace:
    """Per-request notes collected while building (the generator is a shared
    singleton serving concurrent requests, so this is passed, not stored)."""

    budget_substitutions: list[BudgetSubstitution] = field(default_factory=list)
    # Anchor cards an LLM (blend curation or compose) chose — spec §24.
    llm_anchor_names: set[str] = field(default_factory=set)


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


# Cosine similarity floor for a budget stand-in. Below it the "similar" card
# is a different card that happens to share a few features.
_MIN_SUBSTITUTE_SIMILARITY = 0.55

_DROP_REASON_TEXT = {
    "unknown": "no card by that name",
    "not_legal": "not legal in this format",
    "off_color": "outside the deck's colors",
    "over_budget": "over the budget",
    "bracket": "above the requested Commander bracket",
    "excluded": "it is also on the exclude list",
    "no_room": "cut to fit the deck size",
}


@lru_cache(maxsize=1)
def _sideboard_staples() -> dict[str, list[str]]:
    path = DATA_DIR / "sideboard_staples.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key: list(names) for key, names in data.items() if not key.startswith("_")}


class DeckGenerator:
    def __init__(self, repository: CardRepository, validator: DeckValidator) -> None:
        self.repository = repository
        self.validator = validator

    def generate(self, request: GenerateDeckRequest) -> DeckResponse:
        trace = _BuildTrace()
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

        if request.format == "commander" and not request.commander_name and request.prompt:
            named = self._commander_named_in(request.prompt, list(request.colors))
            if named:
                request = request.model_copy(update={"commander_name": named})

        # The user's constraints (explicit fields plus what the brief stated),
        # before archetype anchors are merged in. Persisted on the response so
        # a refine keeps them (budget, excludes, ...).
        user_request = request

        # Built-in archetype seeds: when the brief names known shell(s) that
        # the tournament corpus doesn't cover (Burn, Tron, Yawgmoth, ...), we
        # inject canonical anchor cards into include_cards and merge the
        # archetype's tags. If the brief matches multiple archetypes (e.g.
        # "burn + lifegain", "boros burn into heliod combo"), they are
        # blended into a synthetic hybrid before being applied. See
        # app/services/builtin_archetypes.py for the seed map.
        matches = detect_builtin_archetypes(request.prompt, request.format)
        # A seed outside the requested colors cannot contribute cards (color
        # gating drops them); it would only pollute the blend's name and tags.
        matches = prefer_color_compatible(matches, list(request.colors))
        if request.archetype_name:
            # "Build this alternative": a named builtin seed wins; a named
            # corpus shell is honored in retrieval.
            forced = next(
                (b for b in BUILTIN_ARCHETYPES
                 if b.display_name.lower() == request.archetype_name.lower() and request.format in b.formats),
                None,
            )
            matches = [forced] if forced else []
        builtin = blend_archetypes(matches, request.format) if matches else None

        # Compose-from-scratch fallback: when the brief has substance but no
        # builtin matched, ask Claude to compose ~30 anchor cards instead of
        # letting the corpus pick a near-miss shell. Synthesizes a transient
        # BuiltinArchetype so the rest of the pipeline doesn't change.
        # Fast-competitive stays on known shells; it never composes a new one.
        if builtin is None and request.prompt and request.prompt.strip() and request.mode != "fast-competitive" and not request.archetype_name:
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
                trace.llm_anchor_names = {name for name, _ in final_composed["anchor_cards"]}
                colors_tuple = tuple(request.colors) if request.colors else ()
                builtin = BuiltinArchetype(
                    # Stable across processes (hash() is salted per process).
                    id="composed-" + hashlib.sha1(request.prompt.encode("utf-8")).hexdigest()[:10],
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
                trace.llm_anchor_names = {name for name, _ in llm_blend["anchor_cards"]}
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
            # Anchors go in as seed cards (quantity preserved, protected from
            # trimming, budget-checked with substitution). They are NOT user
            # includes: include_cards stays what the user asked for, so the
            # "forced card over budget" / "dropped include" reports name only
            # cards the user actually requested.
            anchor_seeds: list[CardRef] = []
            existing_seed_names = {ref.name.lower() for ref in request.seed_cards}
            for name, qty in builtin.anchor_cards:
                if qty <= 0:
                    continue
                if not self.repository.get_card(name):
                    continue
                if name.lower() not in existing_seed_names:
                    anchor_seeds.append(CardRef(name=name, quantity=qty))
            request = request.model_copy(update={
                "colors": request.colors or list(builtin.colors),
                "playstyle_tags": list(dict.fromkeys(list(request.playstyle_tags) + list(builtin.playstyle_tags))),
                "theme_tags": list(dict.fromkeys(list(request.theme_tags) + list(builtin.theme_tags))),
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
            mainboard = self._build_commander_mainboard(base, request, list(commander_identity), requested_tags, commander, trace=trace)
            mainboard, legality_actions = self._enforce_commander_color_identity(mainboard, commander_identity)
            sideboard: list[CardRef] = []
        else:
            outcome = self._retrieve_for_constructed(request, builtin=builtin)
            base = outcome.base
            colors = request.colors or base.colors
            commander = None
            mainboard = self._build_constructed_mainboard(base, request, colors, requested_tags, trace=trace)
            sideboard = self._build_sideboard(base, request, colors, requested_tags, mainboard, trace=trace)
            commander_identity = set(colors)

        validation = self.validator.validate(
            ValidateDeckRequest(format=request.format, mainboard=mainboard, sideboard=sideboard, commander=commander)
        )
        if request.format == "commander" and not validation.is_legal:
            details = "; ".join(validation.errors) or "unknown commander legality failure"
            raise ValueError(
                "Commander generation failed its final legality gate; no deck was returned. "
                f"{details}"
            )
        estimated_price = self._estimate_price(mainboard, sideboard, commander)
        warnings = validation.warnings[:] + include_warnings + legality_actions
        if request.budget is not None and estimated_price is not None and estimated_price > request.budget:
            warnings.append(
                f"Estimated deck price is about ${estimated_price:.2f}, which is above the requested budget of ${request.budget:.2f}."
            )

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
        # The explanation text quotes the confidence, so build it from the
        # final number (it used to print the retrieval-time 0.70 next to a
        # 95% badge).
        outcome = dataclasses.replace(outcome, confidence=round(confidence, 3))
        explanation = self._build_explanation(base, request, colors, mainboard, sideboard, warnings, commander_reason, outcome)
        mechanics = self._build_mechanics(mainboard, commander)
        role_summary = self._build_role_summary(mainboard)
        sections = self._build_sections(base, request, mainboard, sideboard, commander, warnings, commander_reason, outcome)
        mana_curve = self._build_mana_curve(mainboard)
        card_notes = self._build_card_notes(mainboard)
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
            llm_added_cards=sorted(
                card.name for name in trace.llm_anchor_names
                if (card := self.repository.get_card(name)) is not None
                and any(ref.name == card.name for ref in mainboard + sideboard)
            ),
            budget_substitutions=trace.budget_substitutions,
            dropped_includes=self._dropped_includes(request, mainboard, sideboard, commander, commander_identity),
        )
        for dropped in provenance.dropped_includes:
            warnings.append(f"Requested card {dropped.name} was not included ({_DROP_REASON_TEXT[dropped.reason]}).")
        for swap in trace.budget_substitutions:
            saved = f", saves about ${swap.saved_usd:.2f} a copy" if swap.saved_usd else ""
            warnings.append(f"Budget: swapped {swap.original} for {swap.replacement}{saved}.")

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

        # Prose must describe the deck that was built: drop sentences that
        # name cards filtering or the LLM left out of the final list.
        in_deck = {ref.name for ref in mainboard + sideboard} | ({commander} if commander else set())
        grounded, removed = ground_text(strategy_summary, in_deck, self.repository)
        if removed:
            strategy_summary = grounded or (
                f"{title}: built from the {base.name} shell and filled from the {request.format} card pool."
            )
            provenance.notes.append(
                f"Removed {len(removed)} summary sentence(s) that named cards not in this list."
            )

        deck = DeckResponse(
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
        return self._enrich_response(deck, user_request=user_request, outcome=outcome)

    # ── Commander named in a brief ───────────────────────────────────────

    @cached_property
    def _commanders_by_first_name(self) -> dict[str, list[CardRecord]]:
        """"krenko" → [Krenko, Mob Boss; Krenko, Tin Street Kingpin]: legal
        commanders keyed by the part of the name before the comma."""
        index: dict[str, list[CardRecord]] = defaultdict(list)
        for card in self.repository.all_cards():
            if ", " in card.name and self.repository.is_legal_commander(card):
                index[card.name.split(", ", 1)[0].lower()].append(card)
        return index

    def _commander_named_in(self, prompt: str, colors: list[str]) -> str | None:
        """A commander the brief names, for the no-LLM path: a full card name
        first ("Atraxa, Praetors' Voice"), else a legend's first name
        ("Krenko goblins" → the best-ranked Krenko)."""
        for name in sorted(card_mentions(prompt, self.repository)):
            card = self.repository.get_card(name)
            if card is not None and self.repository.is_legal_commander(card):
                return card.name
        for word in re.findall(r"[A-Za-zÀ-ÿ'\-]{3,}", prompt):
            options = self._commanders_by_first_name.get(word.lower())
            if not options:
                continue
            if len(options) == 1:
                return options[0].name
            ranked = self.repository.rank_commanders(colors=colors or None, search=word, limit=10)
            option_names = {card.name for card in options}
            for result in ranked:
                if result.name in option_names:
                    return result.name
            return sorted(option_names)[0]
        return None

    # ── Response enrichment ──────────────────────────────────────────────

    @staticmethod
    def deck_id_for(format_name: str, commander: str | None, mainboard: list[CardRef], sideboard: list[CardRef]) -> str:
        """Stable id for an exact list: same cards → same id, in any process."""
        def canon(refs: list[CardRef]) -> list[tuple[str, int]]:
            merged: Counter[str] = Counter()
            for ref in refs:
                merged[ref.name] += ref.quantity
            return sorted(merged.items())
        payload = json.dumps([format_name, commander or "", canon(mainboard), canon(sideboard)])
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]

    def _enrich_response(
        self,
        deck: DeckResponse,
        *,
        user_request: GenerateDeckRequest,
        outcome: "_RetrievalOutcome",
    ) -> DeckResponse:
        """Attach the spec-level extras that don't change the list itself:
        stable id, persisted constraints, alternatives, color sources and
        pricing transparency."""
        deck.deck_id = self.deck_id_for(deck.format, deck.commander, deck.mainboard, deck.sideboard)
        deck.constraints = DeckConstraints(
            budget=user_request.budget,
            include_cards=list(user_request.include_cards),
            exclude_cards=list(user_request.exclude_cards),
            owned_cards=list(user_request.owned_cards),
            mode=user_request.mode,
            match_type=user_request.match_type,
            bracket=user_request.bracket,
            experience_level=user_request.experience_level,
            prompt=user_request.prompt,
        )
        deck.color_sources = self._color_sources(deck.mainboard, deck.colors)
        owned = {name.lower() for name in user_request.owned_cards}
        unpriced: list[str] = []
        to_complete = 0.0
        priced_any = False
        refs = deck.mainboard + deck.sideboard + ([CardRef(name=deck.commander, quantity=1)] if deck.commander else [])
        for ref in refs:
            card = self.repository.get_card(ref.name)
            if card is None or is_basic_land(card):
                continue
            if card.price_usd is None:
                unpriced.append(card.name)
                continue
            priced_any = True
            if card.name.lower() not in owned:
                to_complete += card.price_usd * ref.quantity
        deck.unpriced_cards = sorted(set(unpriced))
        deck.cost_to_complete_usd = round(to_complete, 2) if priced_any else None
        if deck.unpriced_cards:
            deck.warnings.append(
                f"{len(deck.unpriced_cards)} card(s) have no price data, so the estimate undercounts: "
                + ", ".join(deck.unpriced_cards[:5])
                + ("…" if len(deck.unpriced_cards) > 5 else "")
            )
        deck.alternatives = self._alternatives(outcome, deck)
        deck.game_plan = build_game_plan(
            format_name=deck.format,
            mainboard=deck.mainboard,
            sideboard=deck.sideboard,
            commander=deck.commander,
            tags=deck.playstyle_tags + deck.theme_tags,
            archetypes=[a for a in self.repository.archetypes_for_format(deck.format)
                        if deck.selected_archetype is None or a.name != deck.selected_archetype.name],
            repository=self.repository,
        )
        if deck.format == "commander":
            names = [ref.name for ref in deck.mainboard] + ([deck.commander] if deck.commander else [])
            deck.bracket = bracket_rules.assess(names, self.repository, target=user_request.bracket)
            if user_request.bracket is not None and deck.bracket.estimated > max(user_request.bracket, 2):
                deck.warnings.append(
                    f"This list reads as bracket {deck.bracket.estimated}, above the requested bracket "
                    f"{user_request.bracket}: " + "; ".join(deck.bracket.notes[:2])
                )
        return deck

    def _color_sources(self, mainboard: list[CardRef], colors: list[str]) -> list[ColorSourcePoint]:
        """Per color: mana sources among the lands vs colored pips in spells."""
        sources: Counter[str] = Counter()
        pips: Counter[str] = Counter()
        for ref in mainboard:
            card = self.repository.get_card(ref.name)
            if card is None:
                continue
            if is_land_card(card):
                produced = self._land_produces(card)
                for color in produced:
                    sources[color] += ref.quantity
                continue
            cost = card.mana_cost or "".join(face.mana_cost or "" for face in card.faces)
            for color in "WUBRG":
                pips[color] += cost.count(color) * ref.quantity
        order = [c for c in "WUBRG" if c in set(colors) or sources[c] or pips[c]]
        return [ColorSourcePoint(color=c, sources=sources[c], pips=pips[c]) for c in order]

    _BASIC_COLOR = {"Plains": "W", "Island": "U", "Swamp": "B", "Mountain": "R", "Forest": "G"}

    def _land_produces(self, card: CardRecord) -> set[str]:
        for basic, color in self._BASIC_COLOR.items():
            if basic in card.type_line:  # basic land types, incl. shocks/duals
                return {c for b, c in self._BASIC_COLOR.items() if b in card.type_line}
        text = card.oracle_text or ""
        produced = {c for c in "WUBRG" if "{" + c + "}" in text}
        if "any color" in text or "one color" in text:
            produced |= set("WUBRG")
        if not produced and card.color_identity:
            produced = set(card.color_identity)
        return produced

    def _alternatives(self, outcome: "_RetrievalOutcome", deck: DeckResponse) -> list[DeckAlternative]:
        out: list[DeckAlternative] = []
        chosen = {name.lower() for name in deck.source_archetypes[:1]}
        deck_colors = {c for c in deck.colors if c != "C"}
        for candidate in outcome.candidates:
            if candidate.name.lower() in chosen or len(out) >= 2:
                continue
            # An alternative must be buildable in the requested colors.
            if deck_colors and not set(candidate.colors) <= deck_colors:
                continue
            if deck.selected_archetype is not None and candidate.name == deck.selected_archetype.name:
                continue
            key_cards = [pkg.name for pkg in candidate.metadata.core_cards[:6]] or [
                ref.name for ref in candidate.mainboard if not self._is_land_name(ref.name)
            ][:6]
            out.append(DeckAlternative(
                name=candidate.name,
                source_type="template" if candidate.metadata.evidence == "template" else "corpus",
                colors=list(candidate.colors),
                tags=list(candidate.tags)[:6],
                key_cards=key_cards,
                summary=candidate.strategy,
                commander=candidate.commander,
            ))
        if len(out) < 2 and deck.format != "commander":
            # Curated seeds that fit the colors and playstyle (built through
            # archetype_name, which resolves builtin names).
            wanted = {self._canonicalize_tag(tag) for tag in deck.playstyle_tags}
            taken = {alt.name.lower() for alt in out} | {name.lower() for name in deck.source_archetypes} | {deck.title.lower()}
            for seed in BUILTIN_ARCHETYPES:
                if len(out) >= 2:
                    break
                if deck.format not in seed.formats or seed.display_name.lower() in taken:
                    continue
                if any(seed.display_name.lower() in name for name in taken):
                    continue
                if deck_colors and not set(seed.colors) <= deck_colors:
                    continue
                if wanted and not wanted & {self._canonicalize_tag(tag) for tag in seed.playstyle_tags}:
                    continue
                out.append(DeckAlternative(
                    name=seed.display_name,
                    source_type="template",
                    colors=list(seed.colors),
                    tags=list(seed.playstyle_tags + seed.theme_tags)[:6],
                    key_cards=[name for name, _ in seed.anchor_cards if not self._is_land_name(name)][:6],
                    summary=seed.strategy,
                ))
        return out

    def _is_land_name(self, name: str) -> bool:
        card = self.repository.get_card(name)
        return bool(card and is_land_card(card))

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

        Used whenever the user's brief matched a known builtin shell (and as
        the last resort when a format has no corpus archetypes at all). Synthesizes an ArchetypeRecord so downstream pipeline
        steps (mainboard fill, strategy summary, sections) all run normally.
        """
        # If the archetype carries a mana_base template, strip any hand-
        # listed lands from anchor_cards — they'd otherwise compete with
        # the template's recipe. The template-driven materialization runs
        # later in _materialize_mana_base via outcome.notes plumbing.
        def _is_land(name: str) -> bool:
            card = self.repository.get_card(name)
            return bool(card and is_land_card(card))

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
                f"Your brief named the {builtin.display_name} archetype; built from its curated seed instead of a corpus shell.",
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

        if request.archetype_name:
            named = [a for a in self.repository.archetypes_for_format(request.format)
                     if a.name.lower() == request.archetype_name.lower()]
            if named:
                others = self.repository.top_archetypes(
                    format_name=request.format, colors=request.colors,
                    theme_tags=request.playstyle_tags + request.theme_tags, limit=4, strict_colors=True,
                )
                base = named[0]
                return _RetrievalOutcome(
                    base=base,
                    candidates=[base] + [a for a in others if a.name != base.name],
                    source_type="template" if base.metadata.evidence == "template" else "corpus",
                    confidence=min(1.0, 0.45 + 0.05 * min(10, base.source_count)),
                    evidence_count=base.source_count,
                    retrieved_from=[base.name],
                    fallback_used=False,
                    notes=[f"Built from the {base.name} shell you picked."],
                )

        # Fast-competitive: the most-played shell in the colors (meta
        # presence), not the closest theme match.
        retrieval_tags = [] if request.mode == "fast-competitive" else request.playstyle_tags + request.theme_tags
        # Strict color subset first — stops a 4C shell from beating a 2C match.
        candidates = self.repository.top_archetypes(
            format_name=request.format,
            colors=request.colors,
            theme_tags=retrieval_tags,
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
                source_type="template" if base.metadata.evidence == "template" else "corpus",
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
                source_type="template" if archetype.metadata.evidence == "template" else "corpus",
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
                source_type="template" if selected.metadata.evidence == "template" else "corpus",
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
        if not intent.include_cards and not intent.exclude_cards:
            # No LLM (or it found no cards): read "add 4x X", "cut Y",
            # "swap A for B" deterministically.
            includes, excludes, quantities = self._parse_refine_cards(prompt)
            intent = intent.model_copy(update={
                "include_cards": includes, "exclude_cards": excludes, "include_quantities": quantities,
            })

        previous = deck.constraints
        current_price = deck.estimated_price_usd or 0
        if intent.budget is not None:
            budget: float | None = intent.budget
        elif intent.scale_budget_by is not None and current_price > 0:
            budget = current_price * intent.scale_budget_by
        else:
            # Keep the budget the deck was built under (it used to be dropped,
            # so "add 4x Lightning Helix" to a $50 deck came back at $194).
            budget = previous.budget

        original_tags = deck.playstyle_tags or ["midrange"]
        playstyle_tags = [t for t in original_tags if t not in intent.remove_playstyle_tags]
        for tag in intent.add_playstyle_tags:
            if tag not in playstyle_tags:
                playstyle_tags.append(tag)
        if not playstyle_tags:
            playstyle_tags = ["midrange"]

        commander_lower = (deck.commander or "").lower()
        # Constraints accumulate across refinements: earlier excludes stay
        # excluded unless this refinement asks for the card back.
        readded = {name.lower() for name in intent.include_cards}
        merged_excludes = list(dict.fromkeys(
            [name for name in previous.exclude_cards if name.lower() not in readded] + intent.exclude_cards
        ))
        removed = {name.lower() for name in intent.exclude_cards}
        merged_includes = list(dict.fromkeys(
            [name for name in previous.include_cards if name.lower() not in removed] + intent.include_cards
        ))
        exclude_set = {name.lower() for name in merged_excludes}
        seed_cards = [
            ref for ref in deck.mainboard
            if ref.name.lower() != commander_lower and ref.name.lower() not in exclude_set
        ]
        for name in intent.include_cards:
            resolved = self.repository.get_card(name)
            canonical = resolved.name if resolved else name
            # A stated count ("add 4x Lightning Bolt") is the target number of
            # copies; the generator honours seed quantities up to the format's
            # limit. Without a count a new card seeds at one copy, as before.
            requested = intent.requested_copies(name) or intent.requested_copies(canonical)
            existing_index = next(
                (i for i, ref in enumerate(seed_cards) if ref.name.lower() == canonical.lower()),
                None,
            )
            if existing_index is None:
                seed_cards.append(CardRef(name=canonical, quantity=requested or 1))
            elif requested and seed_cards[existing_index].quantity < requested:
                seed_cards[existing_index] = CardRef(name=canonical, quantity=requested)

        colors = list(dict.fromkeys(deck.colors + intent.color_changes))

        if deck.format != "commander":
            seed_cards = self._preserve_land_count(deck, seed_cards, colors, keep_lands=not intent.color_changes)

        request = GenerateDeckRequest(
            format=deck.format,
            colors=colors,
            playstyle_tags=playstyle_tags,
            theme_tags=deck.theme_tags or [],
            budget=budget,
            commander_name=deck.commander,
            include_cards=merged_includes,
            exclude_cards=merged_excludes,
            seed_cards=seed_cards,
            preserve_mana_base=deck.format != "commander",
            mode=previous.mode,
            experience_level=previous.experience_level,
            match_type=previous.match_type,
            bracket=previous.bracket,
            owned_cards=previous.owned_cards,
        )
        regenerated = self.generate(request)
        # The original brief still describes the deck; refinements append.
        regenerated.constraints.prompt = previous.prompt
        base_title = re.sub(r"( - Refined)+$", "", deck.title)
        regenerated.title = f"{base_title} - Refined"
        diff = diff_decks(deck.mainboard, regenerated.mainboard).to_dict()
        diff["sideboard"] = diff_decks(deck.sideboard, regenerated.sideboard).to_dict()["summary"]
        regenerated.changes = diff
        summary = diff["summary"]
        if prompt:
            regenerated.explanation.append(f"Refinement applied: {prompt}")
        moves = (
            [f"+{e['quantity']} {e['name']}" for e in diff["added"]]
            + [f"+{e['delta']} {e['name']}" for e in diff["increased"]]
            + [f"-{e['quantity']} {e['name']}" for e in diff["removed"]]
            + [f"-{e['delta']} {e['name']}" for e in diff["decreased"]]
        )
        regenerated.explanation.append(
            f"What changed: {', '.join(moves[:10])}{'…' if len(moves) > 10 else ''} "
            f"({summary['total_changes']} card changes)." if moves else "What changed: no mainboard changes."
        )
        if previous.budget is not None and budget == previous.budget and regenerated.estimated_price_usd and regenerated.estimated_price_usd > budget:
            regenerated.warnings.append(
                f"The refined deck costs about ${regenerated.estimated_price_usd:.2f}, over the ${budget:.2f} budget it was built under."
            )
        return regenerated

    _SWAP = re.compile(r"\b(?:swap|replace|trade)\s+(?P<out>.+?)\s+(?:for|with)\s+(?P<in>.+)", re.IGNORECASE)
    _REMOVE = re.compile(r"\b(?:remove|cut|drop|exclude|lose|take out|no more|without|get rid of)\b", re.IGNORECASE)
    _ADD = re.compile(r"\b(?:add|include|play|put in|run|more|bring in|use)\b", re.IGNORECASE)
    _COUNT = re.compile(r"\b(\d+)\s*x?\s*$|\ba playset of\s*$|\bfour (?:copies of )?\s*$", re.IGNORECASE)

    def _parse_refine_cards(self, prompt: str) -> tuple[list[str], list[str], dict[str, int]]:
        includes: list[str] = []
        excludes: list[str] = []
        quantities: dict[str, int] = {}

        def count_before(clause: str, name: str) -> int | None:
            idx = clause.lower().find(name.split(" // ")[0].lower())
            if idx < 0:
                return None
            match = self._COUNT.search(clause[:idx])
            if not match:
                return None
            return int(match.group(1)) if match.group(1) else 4

        for clause in re.split(r"[.;\n]|,|\band then\b", prompt):
            clause = clause.strip()
            if not clause:
                continue
            swap = self._SWAP.search(clause)
            if swap:
                excludes += sorted(card_mentions(swap.group("out"), self.repository) or [])
                for name in sorted(card_mentions(swap.group("in"), self.repository)):
                    includes.append(name)
                    if (n := count_before(swap.group("in"), name)):
                        quantities[name] = n
                continue
            for part in re.split(r"\band\b", clause):
                mentions = sorted(card_mentions(part, self.repository) or card_mentions(" " + part, self.repository))
                if not mentions:
                    continue
                if self._REMOVE.search(part):
                    excludes += mentions
                elif self._ADD.search(part) or self._REMOVE.search(clause) is None:
                    for name in mentions:
                        includes.append(name)
                        if (n := count_before(part, name)):
                            quantities[name] = n
        return list(dict.fromkeys(includes)), list(dict.fromkeys(excludes)), quantities

    def _preserve_land_count(
        self,
        deck: DeckResponse,
        seed_cards: list[CardRef],
        colors: list[str],
        *,
        keep_lands: bool,
    ) -> list[CardRef]:
        """Keep a refined constructed deck at its original land count.

        Excluding a land ("swap the Islands for Mountains") must not shrink the
        mana base: the removed copies come back as on-color basics. When the
        refinement changes colors the old lands are dropped instead, so the
        builder derives a fresh mana base for the new colors.
        """
        def is_land(name: str) -> bool:
            card = self.repository.get_card(name)
            return bool(card and is_land_card(card))

        if not keep_lands:
            return [ref for ref in seed_cards if not is_land(ref.name)]
        original_lands = sum(ref.quantity for ref in deck.mainboard if is_land(ref.name))
        seeded_lands = sum(ref.quantity for ref in seed_cards if is_land(ref.name))
        shortfall = original_lands - seeded_lands
        if shortfall <= 0:
            return seed_cards
        basics = self._basic_lands_for_colors(colors) or ["Wastes"]
        seeded_basics = [ref.name for ref in seed_cards if ref.name in basics]
        # Prefer a basic the deck (or the refinement) already runs.
        target = seeded_basics[0] if seeded_basics else basics[0]
        out = list(seed_cards)
        index = next((i for i, ref in enumerate(out) if ref.name == target), None)
        if index is None:
            out.append(CardRef(name=target, quantity=shortfall))
        else:
            out[index] = CardRef(name=target, quantity=out[index].quantity + shortfall)
        return out

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
        if target == "archidekt":
            return self._export_archidekt(deck)
        return self.export_plain(deck)

    def _build_constructed_mainboard(
        self,
        archetype: ArchetypeRecord,
        request: GenerateDeckRequest,
        colors: list[str],
        requested_tags: list[str],
        trace: _BuildTrace | None = None,
    ) -> list[CardRef]:
        excluded = self._excluded_names(request.exclude_cards)
        counts = Counter[str]()
        core_names = {package.name for package in archetype.metadata.core_cards[:18]}

        for ref in archetype.mainboard:
            card = self.repository.get_card(ref.name)
            if not card or card.name.lower() in excluded:
                continue
            if not self._is_card_legal_record(card, request.format) or not self._matches_color_request(card, colors):
                continue
            # Lands are not budget-exempt here: pricey duals are usually the
            # most expensive part of an aggro deck, and _add_lands backfills
            # any shortfall with basics.
            if not self._fits_budget_request(card, request.budget, exempt_lands=False):
                continue
            desired_qty = max(ref.quantity, 2 if ref.name in core_names and not is_land_card(card) else ref.quantity)
            counts[card.name] = min(desired_qty, self._copy_limit(card, request.format) or desired_qty)

        for include_name in request.include_cards:
            card = self.repository.get_card(include_name)
            if card and self._matches_color_request(card, colors) and self._is_card_legal_record(card, request.format):
                counts[card.name] = max(counts[card.name], 2)

        # Seed from prior deck (refine path): preserve original quantities for cards that still pass all filters
        seeded_land_total = 0
        protected: set[str] = set()
        for ref in request.seed_cards:
            card = self.repository.get_card(ref.name)
            if not card or card.name.lower() in excluded:
                continue
            if is_land_card(card):
                if not request.preserve_mana_base:
                    continue
                # A refine seeds the previous mana base (see
                # _preserve_land_count). Keep it as-is: it is the land target.
                if self._is_card_legal_record(card, request.format) and (
                    is_basic_land(card) or self._matches_color_request(card, colors)
                ):
                    limit = self._copy_limit(card, request.format)
                    counts[card.name] = min(ref.quantity, limit or ref.quantity)
                    seeded_land_total += counts[card.name]
                continue
            if not self._is_card_legal_record(card, request.format) or not self._matches_color_request(card, colors):
                continue
            if not self._fits_budget_request(card, request.budget):
                card = self._budget_substitute(
                    card, format_name=request.format, budget=request.budget, excluded=excluded,
                    taken=set(counts), fits=lambda c: self._matches_color_request(c, colors), trace=trace,
                )
                if card is None:
                    continue
            limit = self._copy_limit(card, request.format)
            # A seed's quantity is the target (it overrides the include
            # path's default of two copies).
            counts[card.name] = min(ref.quantity, limit or ref.quantity)
            protected.add(card.name)
        # Cards the user explicitly asked for are cut last of all.
        requested = {card.name for name in request.include_cards if (card := self.repository.get_card(name))}
        protected |= requested
        if seeded_land_total:
            # The seeded mana base replaces the retrieved shell's lands, which
            # were added by the archetype loop above (e.g. Steam Vents pushing
            # out the Mountains a user just swapped in).
            seeded_land_names = {
                card.name
                for ref in request.seed_cards
                if (card := self.repository.get_card(ref.name)) is not None and is_land_card(card)
            }
            for name in list(counts):
                card = self.repository.get_card(name)
                if card and is_land_card(card) and name not in seeded_land_names:
                    del counts[name]

        target_lands = seeded_land_total or self._target_land_count(archetype, requested_tags)
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
        pool_ranked = self._rank_cards(request.format, colors, requested_tags, request.budget, excluded)
        if request.mode == "creative-but-viable":
            # Flex slots from a rotated slice of the themed pool instead of
            # the corpus packages: same quality band, different picks.
            ranked_candidates = self._novelty_order(pool_ranked, request)
        elif from_builtin:
            ranked_candidates = pool_ranked
        else:
            ranked_candidates = [item["name"] for item in package_candidates] + pool_ranked
        nonland_target = CONSTRUCTED_DECK_SIZE - target_lands
        while self._nonland_total(counts) < nonland_target:
            if not self._add_ranked_candidate(counts, ranked_candidates, request.format, colors, request.budget, excluded):
                break
        protected |= self._ensure_color_presence(
            counts, colors, ranked_candidates, request.format, excluded, protected,
            fits=lambda c: self._matches_color_request(c, colors) and self._fits_budget_request(c, request.budget),
            copies=2,
        )
        if not seeded_land_total:
            # A seeded (refined) mana base is kept as the user left it; only a
            # fresh build derives lands from the shell and rebalances basics.
            self._add_lands_from_packages(counts, colors, target_lands, archetype.metadata.land_packages, request.format, budget=request.budget)
        self._trim_to_size(counts, colors, target_lands, protected, requested)
        max_fill_iters = 200
        for _ in range(max_fill_iters):
            if self._total_cards(counts) >= CONSTRUCTED_DECK_SIZE:
                break
            self._add_best_remaining(counts, ranked_candidates, request.format, colors, excluded)
        self._enforce_total_budget(
            counts, request.budget, request.format, colors, ranked_candidates, excluded, requested, trace,
            fits=lambda c: self._matches_color_request(c, colors),
        )
        return self._counts_to_refs(counts)

    def _build_sideboard(
        self,
        archetype: ArchetypeRecord,
        request: GenerateDeckRequest,
        colors: list[str],
        requested_tags: list[str],
        mainboard: list[CardRef],
        trace: _BuildTrace | None = None,
    ) -> list[CardRef]:
        """A full 15-card sideboard for best-of-three (none for best-of-one).

        Curated archetype sideboards and corpus packages go first; the rest is
        filled round-robin across the matchup classes in
        ``sideboard_classes`` from the whole legal, on-color, in-budget pool,
        so a shell without a corpus sideboard still gets real answers instead
        of 0-6 cards (Standard and Pioneer used to ship empty sideboards).
        """
        if request.match_type == "bo1":
            return []
        excluded = self._excluded_names(request.exclude_cards)
        counts = Counter[str]()
        main_counts: Counter[str] = Counter()
        for ref in mainboard:
            resolved = self.repository.get_card(ref.name)
            main_counts[resolved.name if resolved else ref.name] += ref.quantity

        def room_for(card: CardRecord) -> int:
            limit = self._copy_limit(card, request.format)
            if limit is None:
                return SIDEBOARD_SIZE
            return max(0, limit - main_counts[card.name] - counts[card.name])

        def eligible(card: CardRecord | None) -> bool:
            return (
                card is not None
                and card.name.lower() not in excluded
                and not is_land_card(card)
                and self._is_card_legal_record(card, request.format)
                and self._matches_color_request(card, colors)
                and self._fits_budget_request(card, request.budget, exempt_lands=False)
            )

        def add(card: CardRecord, quantity: int) -> None:
            take = min(quantity, room_for(card), SIDEBOARD_SIZE - self._total_cards(counts))
            if take > 0:
                counts[card.name] += take

        # Curated sideboard (builtin seeds: Burn → Smash to Smithereens, ...).
        for ref in archetype.sideboard:
            card = self.repository.get_card(ref.name)
            if eligible(card):
                add(card, ref.quantity)
        preferred_packages = archetype.metadata.sideboard_packages or archetype.metadata.matchup_tech_packages
        for package in preferred_packages:
            card = self.repository.get_card(package.name)
            if eligible(card):
                add(card, int(round(package.average_quantity or 1)))

        if self._total_cards(counts) < SIDEBOARD_SIZE:
            pools = self._sideboard_class_pools(request.format)
            covered = {cls.key for name in counts if (c := self.repository.get_card(name)) and (cls := classify(c))}
            # Classes the deck doesn't already answer come first.
            order = [cls for cls in SIDEBOARD_CLASSES if cls.key not in covered] + [
                cls for cls in SIDEBOARD_CLASSES if cls.key in covered
            ]
            cursors = {cls.key: 0 for cls in order}
            progressed = True
            while self._total_cards(counts) < SIDEBOARD_SIZE and progressed:
                progressed = False
                for cls in order:
                    pool = pools.get(cls.key, [])
                    while cursors[cls.key] < len(pool):
                        card = self.repository.get_card(pool[cursors[cls.key]])
                        cursors[cls.key] += 1
                        if eligible(card) and counts[card.name] == 0 and main_counts[card.name] == 0:
                            add(card, 2)
                            progressed = True
                            break
                    if self._total_cards(counts) >= SIDEBOARD_SIZE:
                        break
        if self._total_cards(counts) < SIDEBOARD_SIZE:
            # Small pools (e.g. a fresh Standard) can run out of classified
            # answers; finish with the best-ranked on-color interaction.
            for name in self._rank_cards(request.format, colors, ["interaction"], request.budget, excluded):
                if self._total_cards(counts) >= SIDEBOARD_SIZE:
                    break
                card = self.repository.get_card(name)
                if eligible(card) and counts[card.name] == 0 and main_counts[card.name] == 0:
                    add(card, 2)
        return self._counts_to_refs(counts)

    def _sideboard_class_pools(self, format_name: str) -> dict[str, list[str]]:
        """Legal cards per sideboard class, cheapest-to-cast first. Cached
        per format (the card pool is fixed for the process lifetime)."""
        cache = self.__dict__.setdefault("_sideboard_pool_cache", {})
        if format_name in cache:
            return cache[format_name]
        # Ranking signals, strongest first: a curated staple for that class
        # (data/sideboard_staples.json, best-first), how often the corpus
        # plays the card in this format, then cheap-to-cast and priced.
        staples = _sideboard_staples()
        corpus_counts: Counter[str] = Counter()
        for archetype in self.repository.archetypes_for_format(format_name):
            for ref in archetype.mainboard + archetype.sideboard:
                corpus_counts[ref.name] += 1
            for package in archetype.metadata.sideboard_packages + archetype.metadata.matchup_tech_packages:
                corpus_counts[package.name] += 1
        pools: dict[str, list[tuple]] = {cls.key: [] for cls in SIDEBOARD_CLASSES}
        for card in self.repository.all_cards():
            if is_land_card(card) or not self._is_card_legal_record(card, format_name):
                continue
            staple_class = next((key for key, names in staples.items() if card.name in names), None)
            cls_key = staple_class or (cls.key if (cls := classify(card)) else None)
            if cls_key is None:
                continue
            staple_rank = staples[cls_key].index(card.name) if staple_class else len(staples.get(cls_key, ())) + 1
            price = card.price_usd if card.price_usd is not None else 1e6
            pools[cls_key].append((staple_rank, -corpus_counts[card.name], card.mana_value, price, card.name))
        cache[format_name] = {key: [row[-1] for row in sorted(rows)] for key, rows in pools.items()}
        return cache[format_name]

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
        #
        # Color fit is judged on the commander card's color identity, never the
        # archetype row's colors: a U/R "Spellslinger" shell keyed to mono-U
        # Talrand used to win a U/R request, and identity filtering then
        # stripped every red card (36 Islands, zero red).
        requested_set = {color for color in colors if color and color != "C"} if colors else set()

        def identity_of(commander_name: str | None) -> set[str]:
            card = self.repository.get_card(commander_name) if commander_name else None
            return set(card.color_identity or card.colors) if card else set()

        def covers_request(identity: set[str]) -> bool:
            return requested_set.issubset(identity)

        # Brackets 1-2 allow no Game Changers, the commander included.
        banned = self._bracket_exclusions(request)
        candidates = [c for c in candidates if not (c.commander and c.commander.lower() in banned)]
        if requested_set:
            candidates = [c for c in candidates if c.commander and identity_of(c.commander).issubset(requested_set)]
        elif colors and set(colors) == {"C"}:
            candidates = [c for c in candidates if c.commander and not identity_of(c.commander)]
        colorless_only = bool(colors) and set(colors) == {"C"}
        archetype_commander_card = self.repository.get_card(archetype.commander) if archetype.commander else None
        archetype_identity = identity_of(archetype.commander)
        archetype_commander_ok = (
            archetype_commander_card is not None
            and archetype_commander_card.name.lower() not in banned
            and self.repository.is_legal_commander(archetype_commander_card)
            and (
                not archetype_identity if colorless_only
                else (not requested_set or archetype_identity.issubset(requested_set))
            )
        )
        # Shortcut only when the shell's commander can play every requested
        # color; otherwise the card pool may hold one that can (a U/B request
        # used to get mono-B Sheoldred from the Reanimator shell this way).
        if not candidates and archetype_commander_ok and archetype.commander and covers_request(archetype_identity):
            return archetype.commander, f"Selected {archetype.commander} because no stronger commander corpus match was available.", archetype
        # Rank by (covers every requested color, score): a commander that can
        # actually play all requested colors always beats one that can't.
        best_rank: tuple[bool, float] = (False, float("-inf"))
        best_choice: ArchetypeRecord | None = None
        best_reason = ""
        requested_color_set = set(colors)
        requested_tag_set = set(requested_tags)
        for candidate in candidates:
            package = candidate.metadata.commander_package
            if not candidate.commander or package is None:
                continue
            identity = identity_of(candidate.commander)
            color_fit = len(requested_set & identity)
            exact_color_fit = covers_request(identity)
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
            if (exact_color_fit, score) > best_rank:
                best_rank = (exact_color_fit, score)
                best_choice = candidate
                best_reason = (
                    f"Selected {candidate.commander} for color fit ({color_fit}), theme fit ({theme_fit}), "
                    f"support depth ({support_depth}), and commander package coherence ({mechanical_coherence:.0f})."
                )
        pool_commander, pool_reason = self._best_card_pool_commander(colors, requested_tags, banned)
        if pool_commander is not None:
            pool_identity = identity_of(pool_commander)
            pool_score = 18 + len(requested_set & pool_identity) * 8
            pool_score += len(requested_tag_set & {self._canonicalize_tag(tag) for tag in (self.repository.get_card(pool_commander).tags if self.repository.get_card(pool_commander) else [])}) * 8
            if (covers_request(pool_identity), pool_score) > best_rank:
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

    _IDENTITY_MANA_STAPLES = frozenset({"Command Tower", "Arcane Signet", "Exotic Orchard", "Path of Ancestry"})

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
            # These tap for the commander's colors; with a colorless
            # commander they produce nothing.
            if not commander_identity and name in self._IDENTITY_MANA_STAPLES:
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
        trace: _BuildTrace | None = None,
    ) -> list[CardRef]:
        counts = Counter[str]()
        commander_identity = self._commander_identity(commander, colors)
        excluded = self._excluded_names(request.exclude_cards) | self._bracket_exclusions(request)
        # The commander is the 100th card, never one of the 99. Corpus
        # signature packages list it, so exclude it from every fill path.
        if commander:
            excluded.add(commander.lower())
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
            if not card or card.name.lower() in excluded or is_land_card(card):
                continue
            if card.name == commander:
                continue
            if not self._is_card_legal_record(card, request.format):
                continue
            if not self.repository.fits_color_identity(card, commander_identity):
                continue
            if not self._fits_budget_request(card, request.budget):
                card = self._budget_substitute(
                    card, format_name=request.format, budget=request.budget, excluded=excluded,
                    taken=set(counts) | {commander or ""},
                    fits=lambda c: self.repository.fits_color_identity(c, commander_identity), trace=trace,
                )
                if card is None:
                    continue
            if counts[card.name] == 0:
                counts[card.name] = 1  # Commander is singleton.

        # The user's own includes. A request like "Atraxa with Doubling
        # Season" used to come back without it and without a word.
        for name in request.include_cards:
            card = self.repository.get_card(name)
            if not card or card.name.lower() in excluded or card.name == commander:
                continue
            if not self._is_card_legal_record(card, request.format):
                continue
            if not self.repository.fits_color_identity(card, commander_identity):
                continue
            counts[card.name] = max(counts[card.name], 1)

        package = archetype.metadata.commander_package
        if package:
            self._add_package_cards(counts, package.ramp_package, target=COMMANDER_ROLE_TARGETS["ramp"], format_name=request.format, colors=list(commander_identity), excluded=excluded)
            self._add_package_cards(counts, package.draw_package, target=COMMANDER_ROLE_TARGETS["draw"], format_name=request.format, colors=list(commander_identity), excluded=excluded)
            self._add_package_cards(counts, package.interaction_package, target=COMMANDER_ROLE_TARGETS["interaction"], format_name=request.format, colors=list(commander_identity), excluded=excluded)
            self._add_package_cards(counts, package.synergy_packages, target=COMMANDER_ROLE_TARGETS["engine"], format_name=request.format, colors=list(commander_identity), excluded=excluded)
            self._add_package_cards(counts, package.signature_cards, target=COMMANDER_ROLE_TARGETS["payoff"], format_name=request.format, colors=list(commander_identity), excluded=excluded)

        themed_candidates = [item["name"] for item in self.repository.card_packages_by_role_theme(format_name=request.format, role="engine", theme_tags=requested_tags, limit=30)]
        fallback_ranked = self._rank_cards(request.format, list(commander_identity), requested_tags or ["ramp"], request.budget, excluded)
        if request.mode == "creative-but-viable":
            themed_candidates = []
            fallback_ranked = self._novelty_order(fallback_ranked, request, window=150)
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

        requested = {card.name for name in request.include_cards if (card := self.repository.get_card(name))}
        protected = {card.name for ref in request.seed_cards if (card := self.repository.get_card(ref.name))} | requested

        def price_of(name: str | None) -> float:
            card = self.repository.get_card(name) if name else None
            return (card.price_usd or 0.0) if card is not None else 0.0
        fits_identity = lambda c: self.repository.fits_color_identity(c, commander_identity)  # noqa: E731
        protected |= self._ensure_color_presence(
            counts, sorted(commander_identity), ranked_nonlands, request.format, excluded, protected,
            fits=lambda c: fits_identity(c) and self._fits_budget_request(c, request.budget),
            copies=1, cards_per_color=4,
        )
        self._add_lands_from_packages(counts, list(commander_identity), LAND_TARGET_COMMANDER, package.land_package if package else [], request.format, budget=request.budget)
        # Land-aware trim: a refine whose seeds overflow 99 used to lose
        # 1-4 lands because the old trim always cut basics first.
        self._trim_to_size(counts, list(commander_identity), LAND_TARGET_COMMANDER, protected, requested, deck_size=COMMANDER_DECK_SIZE)
        while self._total_cards(counts) < COMMANDER_DECK_SIZE:
            self._add_basic_land(counts, list(commander_identity))
        # Brackets 1-2: no two-card combos. Cut one piece of each and refill.
        for victim in bracket_rules.combo_pieces_to_cut(set(counts) | {commander or ""}, request.bracket, requested | {commander or ""}):
            if counts.pop(victim, 0):
                excluded.add(victim.lower())
                if not self._add_ranked_candidate(counts, ranked_nonlands, request.format, list(commander_identity), request.budget, excluded, commander_name=commander):
                    self._add_basic_land(counts, list(commander_identity))
        self._enforce_total_budget(
            counts, request.budget, request.format, list(commander_identity), ranked_nonlands, excluded,
            requested | ({commander} if commander else set()), trace, fits=fits_identity,
            fixed_cost=price_of(commander),
        )
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
        total_lands = sum(ref.quantity for ref in mainboard if (card := self.repository.get_card(ref.name)) and is_land_card(card))
        role_summary = self._build_role_summary(mainboard)
        provenance_blurb = {
            "corpus": f"Started from the {archetype.name} shell, backed by {outcome.evidence_count} corpus deck(s) of supporting evidence.",
            "fallback": f"No matching corpus shell was found — the deck was assembled from the legal card pool using deterministic role and color filters (low confidence: {outcome.confidence:.2f}).",
            "hybrid": f"Started from the {archetype.name} shell but most slots were filled by deterministic fallbacks (mixed confidence: {outcome.confidence:.2f}).",
            "builtin": f"Assembled from the curated {archetype.name} seed your brief matched, then filled from the legal card pool.",
            "template": f"Started from the {archetype.name} template — a curated archetype shape, not observed tournament results — and filled from the legal card pool.",
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
            "builtin": f"Built from the curated {archetype.name} seed. Confidence {outcome.confidence:.2f}.",
            "template": f"Template shell (curated, not observed results). Confidence {outcome.confidence:.2f}.",
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
            if not card or is_land_card(card):
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
            if card.name not in key_cards[role] and len(key_cards[role]) < 4 and not is_land_card(card):
                key_cards[role].append(card.name)
        ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        return [DeckRoleSummary(role=role, total_cards=total, key_cards=key_cards[role]) for role, total in ordered]

    def _build_mana_curve(self, refs: list[CardRef]) -> list[ManaCurvePoint]:
        buckets = Counter[int]()
        for ref in refs:
            card = self.repository.get_card(ref.name)
            if not card or is_land_card(card):
                continue
            buckets[min(6, int(card.mana_value))] += ref.quantity
        return [ManaCurvePoint(mana_value=value, card_count=buckets[value]) for value in range(0, 7)]

    def _build_card_notes(self, refs: list[CardRef]) -> list[DeckCardExplanation]:
        notes: list[DeckCardExplanation] = []
        for ref in refs:
            card = self.repository.get_card(ref.name)
            if not card or is_basic_land(card):
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
            score += 2 if is_land_card(card) else max(0, 5 - card.mana_value)
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
            # Synthesized-from-template shells: the shape is curated, the
            # "evidence" is not observed play.
            "template": 0.45,
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

    def _budget_substitute(
        self,
        card: CardRecord,
        *,
        format_name: str,
        budget: float | None,
        excluded: set[str],
        taken: set[str],
        fits,
        trace: _BuildTrace | None,
    ) -> CardRecord | None:
        """Cheapest-fitting stand-in for an over-budget seed card: a similar
        card (same primary role, land-ness) that is legal, inside the color
        constraint, priced, and under the per-card budget cap. Recorded in
        the trace so provenance can show the swap."""
        role = self._primary_role(card)
        card_type = self.repository.primary_type_for(card)
        for hit in self._retriever.similar_to(card.name, k=80):
            if hit.score < _MIN_SUBSTITUTE_SIMILARITY:
                break  # hits are sorted; nothing closer follows
            alt = self.repository.get_card(hit.name)
            if alt is None or alt.name == card.name or alt.name in taken or alt.name.lower() in excluded:
                continue
            # A stand-in has to do the same job at about the same speed:
            # same card type and role, mana value within one.
            if is_land_card(alt) != is_land_card(card) or self._primary_role(alt) != role:
                continue
            if self.repository.primary_type_for(alt) != card_type or abs(alt.mana_value - card.mana_value) > 1:
                continue
            if not self._is_card_legal_record(alt, format_name) or not fits(alt):
                continue
            if alt.price_usd is None or not self._fits_budget_request(alt, budget, exempt_lands=False):
                continue
            if trace is not None:
                saved = round(card.price_usd - alt.price_usd, 2) if card.price_usd is not None else None
                trace.budget_substitutions.append(
                    BudgetSubstitution(original=card.name, replacement=alt.name, saved_usd=saved)
                )
            return alt
        return None

    @cached_property
    def _retriever(self):
        from app.services.vector_retrieval import CardVectorRetriever

        return CardVectorRetriever(self.repository)

    def _dropped_includes(
        self,
        request: GenerateDeckRequest,
        mainboard: list[CardRef],
        sideboard: list[CardRef],
        commander: str | None,
        identity: set[str],
    ) -> list[DroppedInclude]:
        present = {ref.name for ref in mainboard + sideboard} | ({commander} if commander else set())
        excluded = self._excluded_names(request.exclude_cards)
        dropped: list[DroppedInclude] = []
        for name in request.include_cards:
            card = self.repository.get_card(name)
            if card is not None and card.name in present:
                continue
            if card is None:
                reason = "unknown"
            elif card.name.lower() in excluded:
                reason = "excluded"
            elif not self._is_card_legal_record(card, request.format):
                reason = "not_legal"
            elif request.format == "commander" and not self.repository.fits_color_identity(card, identity):
                reason = "off_color"
            elif request.format != "commander" and not self._matches_color_request(card, list(identity)):
                reason = "off_color"
            elif request.budget is not None and not self._fits_budget_request(card, request.budget):
                reason = "over_budget"
            else:
                reason = "bracket" if request.bracket else "no_room"
            dropped.append(DroppedInclude(name=card.name if card else name, reason=reason))
        return dropped

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
        return copy_limit(card, format_name)

    def _commander_identity(self, commander_name: str | None, fallback_colors: list[str]) -> set[str]:
        if not commander_name:
            return set(fallback_colors)
        commander = self.repository.get_card(commander_name)
        if not commander:
            return set(fallback_colors)
        # An empty identity is real (colorless commanders), not "unknown".
        return set(commander.color_identity or commander.colors)

    def _ordered_commander_identity(self, commander_name: str | None, fallback_colors: list[str]) -> list[str]:
        if not commander_name:
            return fallback_colors
        commander = self.repository.get_card(commander_name)
        if not commander:
            return fallback_colors
        return list(commander.color_identity or commander.colors)

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
    def _fits_budget_request(card: CardRecord, budget: float | None, *, exempt_lands: bool = True) -> bool:
        if budget is None or card.price_usd is None:
            return True
        per_card_cap = max(0.50, min(budget / 20.0, budget * 0.12))
        if exempt_lands and is_land_card(card):
            return True
        return card.price_usd <= per_card_cap

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
                # Corpus packages can be skewed (a single 28-Plains record).
                # Clamp to the range real 60-card decks live in — the
                # validator warns above 27, so never build past it.
                return max(17, min(template_total, 26))
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

    def _add_lands_from_packages(self, counts: Counter[str], colors: list[str], target_lands: int, packages: list[ArchetypePackage], format_name: str = "modern", budget: float | None = None) -> None:
        # Color-identity-aware: a sliver-shaped land package will not leak
        # off-color basics into a narrow-color deck. This filter applies to
        # ALL formats when the caller passed an explicit color list — a UR
        # dual land in a mono-R modern deck is technically legal but is never
        # what the user asked for (the U source is dead weight).
        identity = {color for color in colors if color and color != "C"}
        enforce_identity = format_name == "commander" or bool(colors)
        for package in packages:
            if self._land_total(counts) >= target_lands:
                break
            card = self.repository.get_card(package.name)
            if not card or not is_land_card(card):
                continue
            if not self._is_card_legal_record(card, format_name):
                continue
            # On a budget request the mana base is fair game — pricey duals
            # (often the most expensive cards in the deck) get skipped here
            # and the basics backfill below covers the shortfall.
            if not self._fits_budget_request(card, budget, exempt_lands=False):
                continue
            if enforce_identity and not self.repository.fits_color_identity(card, identity):
                continue
            limit = self._copy_limit(card, format_name)
            if limit is not None and counts[card.name] >= limit:
                continue
            desired = max(1, int(round(package.average_quantity or 1)))
            if limit is not None:
                desired = min(desired, limit - counts[card.name])
            # Never let a single package blow past the land target — a corpus
            # "28 Plains" package would otherwise crowd out every other color.
            desired = min(desired, target_lands - self._land_total(counts))
            if desired <= 0:
                continue
            counts[card.name] += desired
        self._add_lands(counts, colors, target_lands)
        self._ensure_color_sources(counts, colors)

    _BASIC_BY_COLOR = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}

    def _ensure_color_sources(self, counts: Counter[str], colors: list[str], min_sources: int = 4) -> None:
        """Rebalance basic lands so every color's source count tracks its
        share of the deck's mana pips. A corpus land package can be heavily
        skewed toward one color (e.g. mono-W Soul Sisters lands grafted onto
        a WB request), leaving splash-color spells uncastable. Nonbasic
        lands are left as-is; only the basic-land portion is reallocated.
        """
        identity = [c for c in colors if c in self._BASIC_BY_COLOR]
        if len(identity) < 2:
            return
        basic_names = set(self._BASIC_BY_COLOR.values())

        # Pip counts per color across nonland spells (hybrid pips count for
        # both colors — close enough for allocation purposes).
        pips = {c: 0 for c in identity}
        nonbasic_sources = {c: 0 for c in identity}
        basics_total = 0
        land_total = 0
        for name, qty in counts.items():
            card = self.repository.get_card(name)
            if not card:
                continue
            if is_land_card(card):
                land_total += qty
                if name in basic_names:
                    basics_total += qty
                else:
                    for c in identity:
                        if c in (card.color_identity or []):
                            nonbasic_sources[c] += qty
                continue
            cost = card.mana_cost or "".join(face.mana_cost or "" for face in card.faces)
            for c in identity:
                pips[c] += cost.count(c) * qty
        total_pips = sum(pips.values())
        if total_pips == 0 or basics_total == 0:
            return

        # Each color wants sources proportional to its pip share, with a
        # floor so a requested splash is never stranded. Basics cover
        # whatever the nonbasics don't.
        need = {}
        for c in identity:
            floor = min_sources if pips[c] < 8 else 8  # validator warns under 8 sources at 8+ pips
            target_sources = max(floor, round(land_total * pips[c] / total_pips))
            need[c] = max(0.0, float(target_sources - nonbasic_sources[c]))
        need_total = sum(need.values())
        if need_total <= 0:
            return
        alloc = {c: int(basics_total * need[c] / need_total) for c in identity}
        remainder = basics_total - sum(alloc.values())
        for c in sorted(identity, key=lambda c: -(basics_total * need[c] / need_total - alloc[c])):
            if remainder <= 0:
                break
            alloc[c] += 1
            remainder -= 1
        for name in list(counts):
            if name in basic_names:
                del counts[name]
        for c, qty in alloc.items():
            if qty > 0:
                counts[self._BASIC_BY_COLOR[c]] += qty

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
            if not card or card.name.lower() in excluded:
                continue
            if not self._is_card_legal_record(card, format_name):
                continue
            if format_name == "commander":
                if not self.repository.fits_color_identity(card, set(colors)):
                    continue
            elif not self._matches_color_request(card, colors):
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
            if not card or card.name.lower() in excluded_cards:
                continue
            if not allow_lands and is_land_card(card):
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

    def _best_card_pool_commander(
        self, colors: list[str], requested_tags: list[str], banned: set[str] | None = None
    ) -> tuple[str | None, str | None]:
        requested_color_set = set(colors)
        expanded_tags = set(requested_tags)
        for tag in requested_tags:
            expanded_tags.update(THEME_TO_TAGS.get(tag, {tag}))
        requested_real = {color for color in requested_color_set if color and color != "C"}
        best_name: str | None = None
        # (covers every requested color, score): see _select_commander.
        best_rank: tuple[bool, float] = (False, float("-inf"))
        for card in self.repository.all_cards():
            if not self.repository.is_legal_commander(card) or (banned and card.name.lower() in banned):
                continue
            identity = set(card.color_identity or card.colors)
            if requested_color_set == {"C"}:
                # Colorless request: only colorless commanders (Kozilek, Karn...).
                if identity:
                    continue
            elif requested_color_set and (not identity or not identity.issubset(requested_color_set)):
                continue
            tag_score = len(expanded_tags & set(card.tags)) * 12
            color_score = len(identity) * 2
            cost_score = max(0, 6 - card.mana_value)
            score = tag_score + color_score + cost_score
            rank = (requested_real.issubset(identity), score)
            if rank > best_rank:
                best_rank = rank
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
            if not card or is_basic_land(card):
                continue
            weight = 100.0 if is_land_card(card) else 10.0 + card.mana_value
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

    def _trim_to_size(
        self,
        counts: Counter[str],
        colors: list[str],
        target_lands: int,
        protected: set[str],
        requested: set[str] | None = None,
        deck_size: int = CONSTRUCTED_DECK_SIZE,
    ) -> None:
        """Cut a list back to ``deck_size`` without gutting the mana base.

        Spells over the nonland budget go first: unprotected cards, then kept
        cards, and cards the user explicitly requested last. Lands are only
        trimmed down to ``target_lands``. The old
        trim always took basics first, so a refine whose seeds plus a new
        corpus shell overflowed 60 shipped with zero lands.
        """
        nonland_target = deck_size - target_lands
        while (before := self._total_cards(counts)) > deck_size:
            if self._nonland_total(counts) > nonland_target:
                if not self._decrement_nonland(counts, protected):
                    if not self._decrement_nonland(counts, requested or set()):
                        self._decrement_nonland(counts, set())
            elif not self._decrement_basic(counts, colors):
                self._decrement_least_important(counts, "modern")
            if self._total_cards(counts) == before:
                break  # nothing removable; leave it for the validator to report

    def _ensure_color_presence(
        self,
        counts: Counter[str],
        colors: list[str],
        ranked: list[str],
        format_name: str,
        excluded: set[str],
        protected: set[str],
        *,
        fits,
        copies: int,
        cards_per_color: int = 2,
    ) -> set[str]:
        """Every requested color must actually show up on nonland cards.

        A three-color request could come back with no green card at all
        (only the shell's two colors filled). For each missing color, swap in
        the best-ranked candidates of that color for the least important
        unprotected spells. Returns the names added (callers protect them)."""
        added: set[str] = set()
        for color in [c for c in colors if c in "WUBRG"]:
            present = any(
                (card := self.repository.get_card(name)) is not None
                and not is_land_card(card)
                and color in (card.color_identity or card.colors)
                for name, qty in counts.items() if qty > 0
            )
            if present:
                continue
            picked = 0
            for name in ranked:
                if picked >= cards_per_color:
                    break
                card = self.repository.get_card(name)
                if card is None or card.name.lower() in excluded or is_land_card(card) or counts[card.name]:
                    continue
                if color not in (card.color_identity or card.colors) or not fits(card):
                    continue
                if not self._is_card_legal_record(card, format_name):
                    continue
                limit = self._copy_limit(card, format_name)
                take = min(copies, limit) if limit is not None else copies
                for _ in range(take):
                    if not self._decrement_nonland(counts, protected | added):
                        break
                    counts[card.name] += 1
                if counts[card.name]:
                    added.add(card.name)
                    picked += 1
        return added

    def _enforce_total_budget(
        self,
        counts: Counter[str],
        budget: float | None,
        format_name: str,
        colors: list[str],
        ranked: list[str],
        excluded: set[str],
        keep: set[str],
        trace: _BuildTrace | None,
        *,
        fits,
        fixed_cost: float = 0.0,
    ) -> None:
        """Bring the list's total price (plus ``fixed_cost``, e.g. the
        commander) under ``budget``.

        The per-card cap alone let a $75 Commander deck reach $200 (many
        cards just under the cap). Repeatedly swap the most expensive card
        (all copies) that isn't in ``keep`` for the best-ranked cheaper
        candidate; an expensive nonbasic land becomes an on-color basic.
        Every swap is recorded as a budget substitution."""
        if budget is None:
            return

        def price(name: str) -> float:
            card = self.repository.get_card(name)
            return (card.price_usd or 0.0) if card is not None else 0.0

        def total() -> float:
            return fixed_cost + sum(price(name) * qty for name, qty in counts.items())

        tried: set[str] = set()
        for _ in range(120):
            if total() <= budget:
                return
            candidates = [
                (price(name) * qty, name) for name, qty in counts.items()
                if qty > 0 and name not in keep and name not in tried and price(name) > 0
            ]
            if not candidates:
                return
            _, victim = max(candidates)
            tried.add(victim)
            card = self.repository.get_card(victim)
            qty = counts[victim]
            if card is None:
                continue
            replacement: CardRecord | None = None
            if is_land_card(card):
                basics = self._basic_lands_for_colors([c for c in (card.color_identity or colors) if c in colors] or colors)
                replacement = self.repository.get_card(basics[0]) if basics else None
            else:
                for name in ranked:
                    alt = self.repository.get_card(name)
                    if alt is None or alt.name == victim or counts[alt.name] or alt.name.lower() in excluded:
                        continue
                    if is_land_card(alt) or not fits(alt) or not self._is_card_legal_record(alt, format_name):
                        continue
                    if alt.price_usd is None or alt.price_usd >= price(victim):
                        continue
                    limit = self._copy_limit(alt, format_name)
                    if limit is not None and limit < qty:
                        continue
                    replacement = alt
                    break
            if replacement is None:
                continue
            del counts[victim]
            counts[replacement.name] += qty
            if trace is not None:
                trace.budget_substitutions.append(BudgetSubstitution(
                    original=victim, replacement=replacement.name,
                    saved_usd=round(price(victim) - (replacement.price_usd or 0.0), 2),
                ))

    def _decrement_nonland(self, counts: Counter[str], protected: set[str]) -> bool:
        """Remove one copy of the highest-cost unprotected nonland card."""
        candidates: list[tuple[float, str]] = []
        for name, quantity in counts.items():
            card = self.repository.get_card(name)
            if quantity <= 0 or name in protected or not card or is_land_card(card):
                continue
            candidates.append((card.mana_value, name))
        if not candidates:
            return False
        _, name = max(candidates)
        counts[name] -= 1
        if counts[name] <= 0:
            del counts[name]
        return True

    def _decrement_basic(self, counts: Counter[str], colors: list[str]) -> bool:
        for basic_land in reversed(self._basic_lands_for_colors(colors)):
            if counts[basic_land] > 0:
                counts[basic_land] -= 1
                if counts[basic_land] <= 0:
                    del counts[basic_land]
                return True
        return False

    def _trim_excess_land_or_spell(self, counts: Counter[str], colors: list[str]) -> None:
        for basic_land in reversed(self._basic_lands_for_colors(colors)):
            if counts[basic_land] > 0:
                counts[basic_land] -= 1
                if counts[basic_land] <= 0:
                    del counts[basic_land]
                return
        self._decrement_least_important(counts, "modern")

    def _add_best_remaining(
        self,
        counts: Counter[str],
        ranked_candidates: list[str],
        format_name: str,
        colors: list[str],
        excluded: set[str],
    ) -> None:
        """Last-resort fill to reach the deck size: the best remaining legal,
        on-color, non-excluded candidate, else a basic in the deck's colors."""
        for candidate_name in ranked_candidates:
            card = self.repository.get_card(candidate_name)
            if not card or card.name.lower() in excluded:
                continue
            if not self._is_card_legal_record(card, format_name) or not self._matches_color_request(card, colors):
                continue
            limit = self._copy_limit(card, format_name)
            if limit is not None and counts[card.name] >= limit:
                continue
            counts[card.name] += 1
            return
        self._add_basic_land(counts, colors)

    @cached_property
    def _bracket_pool(self) -> tuple[frozenset[str], frozenset[str]]:
        """Mass-land-denial and extra-turn card names in the pool (computed
        once; oracle-text scans over 33k cards are too slow per request)."""
        mld = frozenset(card.name for card in self.repository.all_cards() if bracket_rules.is_mass_land_denial(card))
        extra = frozenset(card.name for card in self.repository.all_cards() if bracket_rules.is_extra_turn(card))
        return mld, extra

    def _bracket_exclusions(self, request: GenerateDeckRequest) -> set[str]:
        if request.format != "commander" or request.bracket is None or request.bracket >= 4:
            return set()
        allow = {card.name for name in request.include_cards if (card := self.repository.get_card(name))}
        mld, extra = self._bracket_pool
        return bracket_rules.excluded_for_bracket(request.bracket, allow, mld, extra)

    @staticmethod
    def _novelty_order(ranked: list[str], request: GenerateDeckRequest, window: int = 60) -> list[str]:
        """Deterministically rotate the top of a ranked list so creative builds
        pick different (still top-ranked) cards than constraint-aware ones,
        and different requests get different rotations."""
        head, tail = ranked[:window], ranked[window:]
        if not head:
            return ranked
        key = json.dumps([request.format, sorted(request.colors), sorted(request.playstyle_tags), request.prompt])
        shift = int(hashlib.sha1(key.encode("utf-8")).hexdigest(), 16) % len(head)
        shift = max(shift, len(head) // 3)
        return head[shift:] + head[:shift] + tail

    def _excluded_names(self, names: list[str]) -> set[str]:
        """Lower-cased exclusions, plus each one's canonical card name, so
        "Picklock Prankster" also excludes "Picklock Prankster // Free the Fae"
        (fill paths check the resolved card's name)."""
        out: set[str] = set()
        for name in names:
            out.add(name.lower())
            card = self.repository.get_card(name)
            if card is not None:
                out.add(card.name.lower())
        return out

    def _primary_role(self, card: CardRecord | None) -> str:
        if not card:
            return "flex slot"
        for tag in card.tags:
            if tag in ROLE_MAP:
                return ROLE_MAP[tag]
        if is_land_card(card):
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
            if card and is_land_card(card):
                total += quantity
        return total

    def _nonland_total(self, counts: Counter[str]) -> int:
        return self._total_cards(counts) - self._land_total(counts)

    def _export_arena(self, deck: DeckResponse) -> str:
        # Arena's importer treats every line as a card or a section header,
        # so no title line.
        lines: list[str] = []
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

    def _export_archidekt(self, deck: DeckResponse) -> str:
        """Archidekt text import: "1x Name" lines with a [Category] tag."""
        lines: list[str] = []
        if deck.commander:
            lines.append(f"1x {deck.commander} [Commander{{top}}]")
        lines.extend(f"{card.quantity}x {card.name}" for card in deck.mainboard)
        lines.extend(f"{card.quantity}x {card.name} [Sideboard]" for card in deck.sideboard)
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
