from __future__ import annotations

import unicodedata
from collections import Counter, defaultdict

from app.models import (
    AnalyzeDeckRequest,
    DeckAdviceGroup,
    DeckAnalysisResponse,
    DeckCardExplanation,
    DeckImprovementSuggestion,
    DeckRoleSummary,
    DeckSwapRecommendation,
    ManaCurvePoint,
    NearestShellComparison,
)
from app.constants import ROLE_MAP
from app.services.card_repository import CardRepository

SIMILARITY_HIGH = 0.60
SIMILARITY_MEDIUM = 0.35


def _norm(s: str) -> str:
    """Normalize card names for comparison: NFKD unicode + casefold handles Æ vs Ae etc."""
    return unicodedata.normalize("NFKD", s).casefold()
from app.services.deck_validator import DeckValidator
from app.services.llm_service import enrich_deck_analysis


class DeckAnalysisService:
    def __init__(self, repository: CardRepository, validator: DeckValidator) -> None:
        self.repository = repository
        self.validator = validator

    def analyze(self, request: AnalyzeDeckRequest) -> DeckAnalysisResponse:
        validation = self.validator.validate(request)
        nearest = self.repository.nearest_archetypes_for_deck(
            format_name=request.format,
            mainboard=request.mainboard,
            commander=request.commander,
            limit=3,
        )
        nearest_archetype = nearest[0][0] if nearest else None
        similarity = nearest[0][1] if nearest else 0.0
        style, archetype_label, similarity_label = self._infer_style(request, nearest_archetype.name if nearest_archetype else None, similarity)
        deck_health, deck_health_explanation = self._infer_health_label(validation.score.total, validation.errors, validation.warnings, similarity)
        role_summary = self._build_role_summary(request.mainboard)
        mana_curve = self._build_mana_curve(request.mainboard)
        card_notes = self._build_card_notes(request.mainboard)
        shell_comparison = self._build_shell_comparison(request, nearest_archetype, similarity)
        strengths, weaknesses, synergy_observations, package_observations = self._analyze_structure(
            request, validation.warnings, nearest_archetype.name if nearest_archetype else None, role_summary, shell_comparison
        )
        advice, suggestions, swaps = self._build_advice(
            request,
            role_summary,
            validation.warnings,
            nearest_archetype,
            shell_comparison,
            mana_curve,
        )
        game_plan_summary = self._build_game_plan_summary(request, style, archetype_label, nearest_archetype.name if nearest_archetype else None)
        play_pattern_summary = self._build_play_pattern_summary(request, role_summary, mana_curve)

        enrichment = enrich_deck_analysis(
            format_name=request.format,
            commander=request.commander,
            card_list=self._format_card_list(request.mainboard),
            role_summary=", ".join(f"{item.role} {item.total_cards}" for item in role_summary[:6]),
            mana_curve_summary=", ".join(f"{p.mana_value}mv:{p.card_count}" for p in mana_curve if p.card_count),
            nearest_archetype=nearest_archetype.name if nearest_archetype else None,
            existing_warnings=validation.warnings,
        )

        return DeckAnalysisResponse(
            format=request.format,
            commander=request.commander,
            deck_health=deck_health,
            deck_health_explanation=deck_health_explanation,
            inferred_style=style,
            inferred_archetype=archetype_label,
            similarity_label=similarity_label,
            nearest_archetypes=[archetype.name for archetype, _ in nearest],
            nearest_shell_comparison=shell_comparison,
            game_plan_summary=enrichment.game_plan_summary if enrichment else game_plan_summary,
            play_pattern_summary=enrichment.play_pattern_summary if enrichment else play_pattern_summary,
            ai_coaching_note=enrichment.ai_coaching_note if enrichment else "",
            strengths=enrichment.strengths if enrichment else strengths,
            weaknesses=enrichment.weaknesses if enrichment else weaknesses,
            synergy_observations=synergy_observations,
            package_observations=package_observations,
            advice=advice,
            improvement_suggestions=suggestions,
            swap_recommendations=swaps,
            validation=validation,
            role_summary=role_summary,
            mana_curve=mana_curve,
            card_notes=card_notes,
        )

    def _infer_style(self, request: AnalyzeDeckRequest, archetype_name: str | None, similarity: float) -> tuple[str, str, str]:
        tag_counts = Counter[str]()
        for ref in request.mainboard:
            card = self.repository.get_card(ref.name)
            if not card:
                continue
            tag_counts.update(card.tags)
        top_tags = [tag for tag, _ in tag_counts.most_common(3)]
        if top_tags:
            style = " / ".join(tag.replace("_", " ").title() for tag in top_tags)
        else:
            style = "Midrange" if request.format != "commander" else "Commander Value"
        archetype_label = archetype_name or (f"{style} shell" if request.format != "commander" else f"{style} commander shell")
        if similarity >= SIMILARITY_HIGH:
            similarity_label = f"Close to the retrieved {archetype_label} shell."
        elif similarity >= SIMILARITY_MEDIUM:
            similarity_label = f"Partially overlaps with the retrieved {archetype_label} shell."
        else:
            similarity_label = "Looks like a hybrid or custom shell inferred from the nearest archetypes."
        return style, archetype_label, similarity_label

    def _build_game_plan_summary(
        self,
        request: AnalyzeDeckRequest,
        style: str,
        archetype_label: str,
        nearest_name: str | None,
    ) -> str:
        commander_note = f" Built around {request.commander} as the commander." if request.commander else ""
        nearest_note = f" It most closely resembles {nearest_name}." if nearest_name else ""
        return f"This deck reads like a {style.lower()} strategy with a game plan closest to {archetype_label}.{commander_note}{nearest_note}"

    def _build_play_pattern_summary(
        self,
        request: AnalyzeDeckRequest,
        role_summary: list[DeckRoleSummary],
        mana_curve: list[ManaCurvePoint],
    ) -> str:
        top_roles = ", ".join(f"{item.role} ({item.total_cards})" for item in role_summary[:3]) or "flex cards"
        early_game = sum(point.card_count for point in mana_curve if point.mana_value <= 2)
        high_end = sum(point.card_count for point in mana_curve if point.mana_value >= 5)
        cadence = "gets on board early and snowballs pressure" if early_game >= 14 else "spends its first turns setting up"
        finisher = "then closes with a higher-end payoff package" if high_end >= 8 else "then tries to convert incremental edges into a win"
        commander_note = " Commander play patterns matter a lot here because the list is expected to lean on its signature engine." if request.format == "commander" else ""
        return f"It will usually {cadence}, leaning most on {top_roles}, and {finisher}.{commander_note}"

    def _analyze_structure(
        self,
        request: AnalyzeDeckRequest,
        warnings: list[str],
        nearest_name: str | None,
        role_summary: list[DeckRoleSummary],
        shell_comparison: NearestShellComparison | None,
    ) -> tuple[list[str], list[str], list[str], list[str]]:
        strengths: list[str] = []
        weaknesses: list[str] = []
        synergy_observations: list[str] = []
        package_observations: list[str] = []

        if nearest_name:
            strengths.append(f"The card mix is close enough to recognizable archetype patterns to map onto {nearest_name}.")
        if role_summary:
            strengths.append(
                f"The deck already shows a defined role mix: {', '.join(f'{item.role} {item.total_cards}' for item in role_summary[:4])}."
            )
        if request.notes:
            package_observations.append(f"Analysis was guided by your note: {request.notes}")
        for warning in warnings[:4]:
            weaknesses.append(warning)

        tag_counts = Counter[str]()
        for ref in request.mainboard:
            card = self.repository.get_card(ref.name)
            if not card or "Land" in card.type_line:
                continue
            tag_counts.update(card.tags)
        if tag_counts:
            top_tags = [tag for tag, count in tag_counts.most_common(3) if count >= 3]
            if top_tags:
                synergy_observations.append(
                    f"The deck's strongest repeated synergy signals are {', '.join(top_tags)}, which explains most of the list's identity."
                )
        if request.format == "commander":
            package_observations.append("Commander structure is judged against ramp, draw, interaction, engine, and payoff package baselines.")
        else:
            package_observations.append("Constructed structure is judged by curve quality, interaction density, and how cleanly threats and payoffs line up.")
        if not weaknesses:
            strengths.append("Validation did not flag any structural failures, so the list is at least coherent on paper.")
        if shell_comparison and nearest_name:
            if shell_comparison.missing_cards:
                package_observations.append(
                    f"The nearest-shell diff shows concrete stock cards to compare against: {', '.join(shell_comparison.missing_cards[:4])}."
                )
            if shell_comparison.off_plan_cards:
                weaknesses.append(
                    f"Some slots look custom rather than shell-aligned, especially {', '.join(shell_comparison.off_plan_cards[:4])}."
                )
        if nearest_name:
            package_observations.append("Nearest-shell comparison is an inference from retrieved archetypes, not a claim that the list is an exact stock build.")
        package_observations.append(
            "Exact add/cut ideas combine nearest-shell overlap with format-legal full-card-pool recommendations, so they are not limited to the local archetype package list."
        )
        return strengths, weaknesses, synergy_observations, package_observations

    def _build_advice(
        self,
        request: AnalyzeDeckRequest,
        role_summary: list[DeckRoleSummary],
        warnings: list[str],
        nearest_archetype,
        shell_comparison: NearestShellComparison | None,
        mana_curve: list[ManaCurvePoint],
    ) -> tuple[DeckAdviceGroup, list[DeckImprovementSuggestion], list[DeckSwapRecommendation]]:
        role_counts = {item.role: item.total_cards for item in role_summary}
        advice = DeckAdviceGroup()
        suggestions: list[DeckImprovementSuggestion] = []
        dominant_tags = self._dominant_tags(request.mainboard)
        deck_names = [ref.name for ref in request.mainboard if ref.quantity > 0]
        colors = self.repository.infer_deck_colors(deck_names, request.commander)

        if role_counts.get("interaction", 0) >= (8 if request.format == "commander" else 6):
            advice.keep_doing.append("Keep the current interaction core; it gives the deck a real chance to answer opposing plans.")
        if role_counts.get("engine", 0) + role_counts.get("payoff", 0) >= (10 if request.format == "commander" else 8):
            advice.keep_doing.append("Keep leaning into the deck's central engine and payoff package instead of diluting the theme.")
        advice.watch_out_for.extend(warnings[:4])

        if role_counts.get("interaction", 0) < (8 if request.format == "commander" else 6):
            advice.add_more_of.append("Add more cheap interaction so the deck can survive to its core plan.")
            suggestions.append(self._suggest_package(request, "interaction", nearest_archetype, dominant_tags, colors))
        if role_counts.get("mana development", 0) < (8 if request.format == "commander" else 2):
            advice.add_more_of.append("Increase mana development or smoothing so the deck reaches its key turns more consistently.")
            suggestions.append(self._suggest_package(request, "ramp", nearest_archetype, dominant_tags, colors))
        if role_counts.get("card advantage", 0) < (8 if request.format == "commander" else 4):
            advice.add_more_of.append("Add more card advantage so the deck does not run out of gas after the first exchange.")
            suggestions.append(self._suggest_package(request, "draw", nearest_archetype, dominant_tags, colors))
        if role_counts.get("threat", 0) < (18 if request.format == "commander" else 12):
            advice.add_more_of.append("Add a few more real threats or payoffs so the deck can actually close games.")
            suggestions.append(self._suggest_package(request, "engine", nearest_archetype, dominant_tags, colors))

        if warnings:
            if any("Land count looks low" in warning or "mana base" in warning.lower() for warning in warnings):
                advice.possible_upgrades.append("Start by fixing the mana base before tuning narrower synergy slots.")
            if any("Commander decks usually want more ramp" in warning for warning in warnings):
                advice.possible_upgrades.append("Bring commander ramp closer to the usual baseline before adding more cute synergy pieces.")

        if request.format != "commander":
            advice.cut_some_of.append("Trim clunky top-end or off-plan one-ofs before cutting the deck's core interaction or payoff cards.")
        else:
            advice.cut_some_of.append("Trim low-impact theme cards before cutting ramp, draw, or interaction baselines.")

        if nearest_archetype:
            advice.possible_upgrades.append(
                f"Compare your list against {nearest_archetype.name} and borrow the most common support package rather than swapping cards at random."
            )
        else:
            advice.possible_upgrades.append("Use cards that reinforce the deck's strongest repeated tags instead of adding isolated pet cards.")
        advice.possible_upgrades.append(
            "Use the exact add/cut ideas as the first tuning pass; they combine nearest-shell gaps with full-card-pool role candidates."
        )

        deduped_suggestions = [suggestion for suggestion in suggestions if suggestion.candidate_cards]
        swaps = self._build_swap_recommendations(
            request=request,
            role_counts=role_counts,
            dominant_tags=dominant_tags,
            nearest_archetype=nearest_archetype,
            shell_comparison=shell_comparison,
            mana_curve=mana_curve,
            colors=colors,
        )
        return advice, deduped_suggestions[:4], swaps

    def _suggest_package(
        self,
        request: AnalyzeDeckRequest,
        role: str,
        nearest_archetype,
        dominant_tags: list[str],
        colors: list[str],
    ) -> DeckImprovementSuggestion:
        theme_tags = list(dict.fromkeys((nearest_archetype.tags if nearest_archetype else []) + dominant_tags))
        package_candidates = self.repository.card_packages_by_role_theme(
            format_name=request.format,
            role=role,
            theme_tags=theme_tags,
            limit=5,
        )
        exact_candidates = self.repository.recommend_cards_for_role(
            format_name=request.format,
            role=role,
            colors=colors,
            commander=request.commander,
            theme_tags=theme_tags,
            exclude_names=[ref.name for ref in request.mainboard],
            preferred_names=[item["name"] for item in package_candidates],
            limit=4,
        )
        candidate_names = [item["name"] for item in exact_candidates] or [item["name"] for item in package_candidates[:4]]
        return DeckImprovementSuggestion(
            category=role.title(),
            summary=f"Add a more coherent {role} package instead of isolated singletons.",
            candidate_cards=candidate_names[:4],
        )

    def _build_shell_comparison(self, request: AnalyzeDeckRequest, nearest_archetype, similarity: float) -> NearestShellComparison | None:
        if nearest_archetype is None:
            return None
        comparison = self.repository.compare_deck_to_archetype(mainboard=request.mainboard, archetype=nearest_archetype)
        return NearestShellComparison(
            shell_name=nearest_archetype.name,
            confidence=similarity,
            overlap_cards=comparison["overlap_cards"],
            missing_cards=comparison["missing_cards"],
            off_plan_cards=comparison["off_plan_cards"],
        )

    @staticmethod
    def _infer_health_label(score_total: int, errors: list[str], warnings: list[str], similarity: float) -> tuple[str, str]:
        if errors or score_total < 60:
            return (
                "structurally flawed",
                "The deck has legality errors or significant construction problems that should be addressed first.",
            )
        if score_total >= 85 and similarity >= SIMILARITY_MEDIUM and len(warnings) <= 2:
            return (
                "well-structured",
                "Your deck has strong synergy and aligns closely with a known archetype strategy.",
            )
        if score_total >= 72 and similarity >= SIMILARITY_MEDIUM:
            return (
                "promising but unfinished",
                "Good foundation, but the deck could use more consistency or a tighter focus around its core plan.",
            )
        return (
            "coherent but underpowered",
            "The strategy is readable but individual card quality or synergy depth may limit results.",
        )

    def _build_role_summary(self, refs: list) -> list[DeckRoleSummary]:
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

    def _build_mana_curve(self, refs: list) -> list[ManaCurvePoint]:
        buckets = Counter[int]()
        for ref in refs:
            card = self.repository.get_card(ref.name)
            if not card or "Land" in card.type_line:
                continue
            buckets[min(6, int(card.mana_value))] += ref.quantity
        return [ManaCurvePoint(mana_value=value, card_count=buckets[value]) for value in range(0, 7)]

    def _build_card_notes(self, refs: list) -> list[DeckCardExplanation]:
        notes: list[DeckCardExplanation] = []
        for ref in refs:
            card = self.repository.get_card(ref.name)
            if not card or "Land" in card.type_line:
                continue
            role = self._primary_role(card)
            notes.append(
                DeckCardExplanation(
                    name=card.name,
                    role=role,
                    reason=f"{card.name} is functioning mainly as {role} in this shell.",
                )
            )
            if len(notes) >= 12:
                break
        return notes

    def _primary_role(self, card) -> str:
        for tag in card.tags:
            if tag in ROLE_MAP:
                return ROLE_MAP[tag]
        if "Land" in card.type_line:
            return "mana base"
        if "Creature" in card.type_line:
            return "threat"
        type_line = card.type_line or ""
        if "Instant" in type_line or "Sorcery" in type_line:
            return "interaction"
        if "Planeswalker" in type_line:
            return "threat"
        if "Artifact" in type_line or "Enchantment" in type_line:
            return "engine"
        return "flex"

    def _dominant_tags(self, refs: list) -> list[str]:
        tag_counts = Counter[str]()
        for ref in refs:
            card = self.repository.get_card(ref.name)
            if not card or "Land" in card.type_line:
                continue
            tag_counts.update(tag for tag in card.tags if tag not in {"land", "mana"})
        threshold = max(2, len(refs) // 15)
        return [tag for tag, count in tag_counts.most_common(4) if count >= threshold]

    def _build_swap_recommendations(
        self,
        *,
        request: AnalyzeDeckRequest,
        role_counts: dict[str, int],
        dominant_tags: list[str],
        nearest_archetype,
        shell_comparison: NearestShellComparison | None,
        mana_curve: list[ManaCurvePoint],
        colors: list[str],
    ) -> list[DeckSwapRecommendation]:
        swaps: list[DeckSwapRecommendation] = []
        used_adds: set[str] = set()
        used_cuts: set[str] = set()
        high_end = sum(point.card_count for point in mana_curve if point.mana_value >= 5)

        if shell_comparison:
            for cut_name, add_name in zip(shell_comparison.off_plan_cards[:2], shell_comparison.missing_cards[:2]):
                if cut_name == add_name:
                    continue
                swaps.append(
                    DeckSwapRecommendation(
                        category="Shell Alignment",
                        cut_card=cut_name,
                        add_card=add_name,
                        reason=f"This lines the list up more closely with the retrieved {shell_comparison.shell_name} shell instead of leaving that slot as a custom deviation.",
                    )
                )
                used_cuts.add(cut_name)
                used_adds.add(add_name)

        role_needs = self._role_needs(request.format, role_counts, high_end)
        cut_candidates = self._rank_cut_candidates(
            request=request,
            role_counts=role_counts,
            dominant_tags=dominant_tags,
            shell_comparison=shell_comparison,
            high_end=high_end,
        )

        preferred_names = shell_comparison.missing_cards if shell_comparison else []
        theme_tags = list(dict.fromkeys(dominant_tags + (nearest_archetype.tags if nearest_archetype else [])))
        deck_names = [ref.name for ref in request.mainboard]
        for role, reason in role_needs:
            add_candidates = self.repository.recommend_cards_for_role(
                format_name=request.format,
                role=role,
                colors=colors,
                commander=request.commander,
                theme_tags=theme_tags,
                exclude_names=deck_names + list(used_adds),
                preferred_names=preferred_names,
                limit=6,
            )
            add_choice = next((item for item in add_candidates if item["name"] not in used_adds), None)
            cut_choice = next((item for item in cut_candidates if item["name"] not in used_cuts), None)
            if not add_choice or not cut_choice:
                continue
            add_reason = ", ".join(add_choice["reasons"][:2]) if add_choice["reasons"] else f"fills the deck's {role} gap"
            swaps.append(
                DeckSwapRecommendation(
                    category=role.title(),
                    cut_card=str(cut_choice["name"]),
                    add_card=str(add_choice["name"]),
                    reason=f"Cut {cut_choice['name']} because it {cut_choice['reason']}; add {add_choice['name']} because it {add_reason}. {reason}",
                )
            )
            used_cuts.add(str(cut_choice["name"]))
            used_adds.add(str(add_choice["name"]))
            if len(swaps) >= 5:
                break
        seen_categories: set[str] = set()
        deduped = [s for s in swaps if s.category not in seen_categories and not seen_categories.add(s.category)]  # type: ignore[func-returns-value]
        return deduped[:5]

    def _rank_cut_candidates(
        self,
        *,
        request: AnalyzeDeckRequest,
        role_counts: dict[str, int],
        dominant_tags: list[str],
        shell_comparison: NearestShellComparison | None,
        high_end: int,
    ) -> list[dict[str, str | float]]:
        off_plan = {_norm(name) for name in (shell_comparison.off_plan_cards if shell_comparison else [])}
        dominant_tag_set = set(dominant_tags)
        candidates: list[dict[str, str | float]] = []
        for ref in request.mainboard:
            card = self.repository.get_card(ref.name)
            if not card or "Land" in card.type_line:
                continue
            role = self._primary_role(card)
            score = 0.0
            reasons: list[str] = []
            card_tags = set(card.tags)
            if _norm(ref.name) in off_plan:
                score += 10
                reasons.append("sits outside the nearest shell")
            if dominant_tag_set and not (dominant_tag_set & card_tags) and role in {"engine", "payoff", "flex", "threat"}:
                score += 5
                reasons.append("does not reinforce the deck's dominant theme")
            if role_counts.get(role, 0) > self._role_target(request.format, role) and role in {"threat", "engine", "flex"}:
                score += 4
                reasons.append(f"is competing in an already crowded {role} slot")
            if high_end >= (10 if request.format == "commander" else 8) and card.mana_value >= 5:
                score += 4
                reasons.append("adds to a top-heavy curve")
            if request.format != "commander" and ref.quantity == 1 and ref.name.lower() not in off_plan:
                score += 2
                reasons.append("looks like a loose singleton rather than a core package piece")
            if score <= 0:
                continue
            candidates.append(
                {
                    "name": ref.name,
                    "score": score,
                    "reason": " and ".join(reasons[:2]),
                }
            )
        candidates.sort(key=lambda item: float(item["score"]), reverse=True)
        return candidates

    def _role_needs(self, format_name: str, role_counts: dict[str, int], high_end: int) -> list[tuple[str, str]]:
        needs: list[tuple[str, str]] = []
        if role_counts.get("interaction", 0) < self._role_target(format_name, "interaction"):
            needs.append(("interaction", "That swap improves the deck's ability to interact before it falls behind."))
        if role_counts.get("mana development", 0) < self._role_target(format_name, "mana development"):
            needs.append(("ramp", "That swap smooths the mana so the deck can reach its key turns more reliably."))
        if role_counts.get("card advantage", 0) < self._role_target(format_name, "card advantage"):
            needs.append(("draw", "That swap gives the list a better chance to keep seeing live cards."))
        if role_counts.get("threat", 0) < self._role_target(format_name, "threat") or high_end == 0:
            needs.append(("threat", "That swap gives the deck a cleaner way to convert its setup into actual pressure.")) 
        if role_counts.get("engine", 0) + role_counts.get("payoff", 0) < (10 if format_name == "commander" else 8):
            needs.append(("engine", "That swap tightens the shell around the deck's main synergy instead of adding more filler."))
        return needs

    def _format_card_list(self, refs: list) -> str:
        lines: list[str] = []
        for ref in refs:
            card = self.repository.get_card(ref.name)
            if card:
                lines.append(f"{ref.quantity}x {card.name} ({card.type_line}, {int(card.mana_value)}mv)")
            else:
                lines.append(f"{ref.quantity}x {ref.name}")
        return "\n".join(lines)

    @staticmethod
    def _role_target(format_name: str, role: str) -> int:
        targets = {
            "commander": {"interaction": 8, "mana development": 8, "card advantage": 8, "threat": 18},
            "constructed": {"interaction": 6, "mana development": 2, "card advantage": 4, "threat": 12},
        }
        bucket = "commander" if format_name == "commander" else "constructed"
        return targets[bucket].get(role, 0)
