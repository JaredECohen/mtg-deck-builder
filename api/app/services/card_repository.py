from __future__ import annotations

import json
import logging
import math
from functools import cached_property
from urllib.parse import quote_plus

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select

logger = logging.getLogger(__name__)

from app.config import ARCHETYPE_PATH, CARD_CACHE_PATH, DATABASE_URL
from app.db import session_scope
from app.services.affiliate import ensure_affiliate_tag
from app.db_models import Archetype, Card
from app.models import (
    ArchetypeMetadata,
    ArchetypePackage,
    ArchetypeRecord,
    CardFaceRecord,
    CardPurchaseLinks,
    CardRecord,
    CardRef,
    CardSearchResult,
    CommanderProfile,
    CommanderSearchResult,
    DataStatusResponse,
)


class CardRepository:
    COLORLESS_SYMBOL = "C"
    ROLE_HINTS = {
        "interaction": {"interaction", "removal", "disruption", "countermagic"},
        "ramp": {"ramp", "mana", "mana_rock", "fixing"},
        "draw": {"draw", "cantrip", "card_advantage", "selection"},
        "engine": {"engine", "spells", "graveyard", "artifact", "tribal", "tokens", "lifegain", "blink"},
        "threat": {"creature", "pressure", "threat", "finisher", "aggro"},
    }

    # Lazily attached by `app.main` after construction so the service can be
    # imported without dragging the refresh thread into test harnesses that
    # do not need it. `None` means "no refresh layer wired up — return data
    # as-is."
    refresh_service: object | None = None

    @staticmethod
    def fits_color_identity(card: "CardRecord", commander_identity: set[str]) -> bool:
        """Return True if the card's color identity is contained within commander_identity."""
        identity = set(card.color_identity or card.colors)
        return not identity or identity.issubset(commander_identity)

    # Order matters: a dual-type card lands in the first matching bucket. Creature
    # comes before Land so an "Artifact Creature — Construct" lands in Creatures
    # and a "Land — Forest" still lands in Lands.
    _PRIMARY_TYPE_ORDER: tuple[str, ...] = (
        "Creature",
        "Planeswalker",
        "Land",
        "Battle",
        "Instant",
        "Sorcery",
        "Enchantment",
        "Artifact",
    )

    @classmethod
    def primary_type_for(cls, card: "CardRecord | None") -> str:
        """Return the bucket name used to group this card in the deck UI.

        Falls back to "Other" when the card is unknown or has no recognized type.
        """
        if not card:
            return "Other"
        type_line = card.type_line or ""
        for bucket in cls._PRIMARY_TYPE_ORDER:
            if bucket in type_line:
                return bucket
        return "Other"

    def card_types_for(self, refs: list["CardRef"], commander: str | None = None) -> dict[str, str]:
        """Build a `name -> primary type` map for every card in a deck list.

        Includes the commander as well so the UI can label it correctly.
        """
        seen: dict[str, str] = {}
        for ref in refs:
            if ref.name in seen:
                continue
            seen[ref.name] = self.primary_type_for(self.get_card(ref.name))
        if commander and commander not in seen:
            seen[commander] = self.primary_type_for(self.get_card(commander))
        return seen

    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(name.lower().split())

    @classmethod
    def _color_request_matches(cls, identity: list[str], requested_colors: list[str] | None) -> bool:
        if not requested_colors:
            return True
        requested = set(requested_colors)
        wants_colorless = cls.COLORLESS_SYMBOL in requested
        requested_colored = requested - {cls.COLORLESS_SYMBOL}
        identity_set = set(identity)
        if wants_colorless and not requested_colored:
            return not identity_set
        if wants_colorless and requested_colored:
            return identity_set.issubset(requested_colored)
        return identity_set.issubset(requested)

    @cached_property
    def _sample_cards(self) -> dict[str, CardRecord]:
        with CARD_CACHE_PATH.open() as handle:
            raw_cards = json.load(handle)
        cards: dict[str, CardRecord] = {}
        for item in raw_cards:
            record = CardRecord.model_validate(item)
            record.purchase_links.amazon_search = ensure_affiliate_tag(
                record.purchase_links.amazon_search, record.name
            )
            cards[self._normalize_name(record.name)] = record
        return cards

    @cached_property
    def _sample_archetypes(self) -> list[ArchetypeRecord]:
        with ARCHETYPE_PATH.open() as handle:
            raw_archetypes = json.load(handle)
        return [ArchetypeRecord.model_validate(item) for item in raw_archetypes]

    # ── Cached corpus ─────────────────────────────────────────────────────────
    # Both cards and archetypes are loaded once from the database (or sample
    # JSON) on first access.  Subsequent calls are O(1) dict/list lookups.

    @cached_property
    def _all_archetypes_cache(self) -> list[ArchetypeRecord]:
        try:
            with session_scope() as session:
                rows = session.scalars(select(Archetype).order_by(Archetype.format, Archetype.name)).all()
            if rows:
                return [self._to_archetype_record(row) for row in rows]
        except (SQLAlchemyError, ModuleNotFoundError) as exc:
            logger.warning("Database unavailable for archetypes, falling back to sample data: %s", exc)
        return sorted(self._sample_archetypes, key=lambda row: (row.format, row.name))

    @cached_property
    def _all_cards_cache(self) -> list[CardRecord]:
        try:
            with session_scope() as session:
                rows = session.scalars(select(Card).order_by(Card.name)).all()
            if rows:
                return [self._to_card_record(row) for row in rows]
        except (SQLAlchemyError, ModuleNotFoundError) as exc:
            logger.warning("Database unavailable for cards, falling back to sample data: %s", exc)
        return sorted(self._sample_cards.values(), key=lambda card: card.name)

    @cached_property
    def _cards_by_name(self) -> dict[str, CardRecord]:
        return {self._normalize_name(card.name): card for card in self._all_cards_cache}

    def all_archetypes(self) -> list[ArchetypeRecord]:
        return self._all_archetypes_cache

    def archetypes_for_format(self, format_name: str) -> list[ArchetypeRecord]:
        return [row for row in self._all_archetypes_cache if row.format == format_name]

    def commander_archetypes_for_name(self, commander_name: str) -> list[ArchetypeRecord]:
        normalized_name = self._normalize_name(commander_name)
        return [
            archetype
            for archetype in self.archetypes_for_format("commander")
            if archetype.commander and self._normalize_name(archetype.commander) == normalized_name
        ]

    def top_archetypes(
        self,
        *,
        format_name: str,
        colors: list[str] | None = None,
        theme_tags: list[str] | None = None,
        limit: int = 5,
        strict_colors: bool = True,
    ) -> list[ArchetypeRecord]:
        """Return the top archetypes for a format, ranked by tag/source fit.

        When `strict_colors=True` (default), an archetype is only considered if
        its declared colors are a subset of the requested colors. This stops a
        4-color shell from outranking a perfect 2-color match purely on
        source_count — the same class of bug we hit on the commander path.

        When `strict_colors=False`, we keep the legacy overlap-scoring behavior
        as a fallback for callers that genuinely want soft matching.
        """
        requested_colors = colors or []
        requested_tags = {self._normalize_name(tag) for tag in (theme_tags or [])}
        requested_color_set = {color for color in requested_colors if color != self.COLORLESS_SYMBOL}
        scored: list[tuple[float, ArchetypeRecord]] = []
        for archetype in self.archetypes_for_format(format_name):
            archetype_colors = set(archetype.colors)
            if requested_colors:
                if strict_colors:
                    if requested_color_set:
                        if not archetype_colors.issubset(requested_color_set):
                            continue
                    elif self.COLORLESS_SYMBOL in requested_colors and archetype_colors:
                        continue
                elif self.COLORLESS_SYMBOL in requested_colors and archetype_colors:
                    continue
            score = max(1.0, float(archetype.source_count))
            if requested_colors:
                overlap = len(requested_color_set & archetype_colors)
                score += overlap * 6
                if self._color_request_matches(archetype.colors, requested_colors):
                    score += 10
            if requested_tags:
                tag_overlap = len(requested_tags & {self._normalize_name(tag) for tag in archetype.tags})
                meta_overlap = len(requested_tags & {self._normalize_name(profile.name) for profile in archetype.metadata.tag_vector})
                score += tag_overlap * 10 + meta_overlap * 8
            score += len(archetype.metadata.signature_cards) * 0.2
            scored.append((score, archetype))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [archetype for _, archetype in scored[:limit]]

    def candidate_commander_packages(
        self,
        *,
        colors: list[str] | None = None,
        theme_tags: list[str] | None = None,
        limit: int = 5,
    ) -> list[ArchetypeRecord]:
        requested_colors = colors or []
        requested_tags = {self._normalize_name(tag) for tag in (theme_tags or [])}
        commanders = [
            archetype
            for archetype in self.archetypes_for_format("commander")
            if archetype.commander and archetype.metadata.commander_package is not None
        ]
        scored: list[tuple[float, ArchetypeRecord]] = []
        for archetype in commanders:
            score = max(1.0, float(archetype.source_count))
            if requested_colors and not self._color_request_matches(archetype.colors, requested_colors):
                continue
            color_overlap = len((set(requested_colors) - {self.COLORLESS_SYMBOL}) & set(archetype.colors))
            score += color_overlap * 6
            if requested_colors and self._color_request_matches(archetype.colors, requested_colors):
                score += 8
            tag_overlap = len(requested_tags & {self._normalize_name(tag) for tag in archetype.tags})
            package_tags = {
                self._normalize_name(tag)
                for pkg in archetype.metadata.commander_package.synergy_packages
                for tag in pkg.tags
            }
            score += tag_overlap * 10 + len(requested_tags & package_tags) * 6
            score += archetype.metadata.commander_package.support_depth
            scored.append((score, archetype))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [archetype for _, archetype in scored[:limit]]

    def rank_commanders(
        self,
        *,
        colors: list[str] | None = None,
        playstyle_tags: list[str] | None = None,
        theme_tags: list[str] | None = None,
        search: str | None = None,
        sort: str = "match",
        limit: int = 25,
    ) -> list[CommanderSearchResult]:
        requested_colors = colors or []
        requested_tags = {
            self._normalize_name(tag)
            for tag in (playstyle_tags or []) + (theme_tags or [])
            if tag
        }
        search_term = self._normalize_name(search or "")
        archetype_map: dict[str, list[ArchetypeRecord]] = {}
        for archetype in self.archetypes_for_format("commander"):
            if not archetype.commander:
                continue
            archetype_map.setdefault(self._normalize_name(archetype.commander), []).append(archetype)
        results: list[CommanderSearchResult] = []
        for card in self.all_cards():
            if not self.is_legal_commander(card):
                continue
            commander_colors = list(card.color_identity or card.colors)
            commander_color_set = set(commander_colors)
            if requested_colors and not self._color_request_matches(commander_colors, requested_colors):
                continue
            if search_term and search_term not in self._normalize_name(card.name):
                continue
            related_archetypes = archetype_map.get(self._normalize_name(card.name), [])
            related_tags = list(dict.fromkeys(
                [tag for archetype in related_archetypes for tag in archetype.tags] + card.tags + self._infer_commander_tags(card)
            ))
            profile_tag_set = {self._normalize_name(tag) for tag in related_tags}
            if requested_tags and not (requested_tags & profile_tag_set):
                continue
            color_fit = len((set(requested_colors) - {self.COLORLESS_SYMBOL}) & commander_color_set)
            theme_fit = len(requested_tags & profile_tag_set)
            popularity = float(sum(archetype.source_count for archetype in related_archetypes))
            support_depth = sum(
                archetype.metadata.commander_package.support_depth
                if archetype.metadata.commander_package else archetype.source_count
                for archetype in related_archetypes
            ) or max(4, len(related_tags) * 2 + len(commander_colors))
            package_richness = max(
                [
                    self._package_richness_from_package(archetype.metadata.commander_package)
                    for archetype in related_archetypes
                ] or [len(related_tags) + len(commander_colors)]
            )
            strategy_summary = (
                related_archetypes[0].strategy
                if related_archetypes
                else self._fallback_commander_strategy(card, related_tags)
            )
            ranking_score = popularity * 3 + support_depth * 2 + package_richness
            ranking_score += color_fit * 8 + theme_fit * 10
            if requested_colors and self._color_request_matches(commander_colors, requested_colors):
                ranking_score += 10
            results.append(
                CommanderSearchResult(
                    name=card.name,
                    colors=commander_colors,
                    tags=related_tags,
                    strategy_summary=strategy_summary,
                    popularity=popularity,
                    support_depth=support_depth,
                    package_richness=package_richness,
                    ranking_score=round(ranking_score, 2),
                    image_uri=card.image_uri or next((face.image_uri for face in card.faces if face.image_uri), None),
                )
            )

        if sort == "name":
            results.sort(key=lambda item: item.name)
        elif sort == "popularity":
            results.sort(key=lambda item: (item.popularity, item.support_depth, item.ranking_score), reverse=True)
        elif sort == "support":
            results.sort(key=lambda item: (item.support_depth, item.package_richness, item.ranking_score), reverse=True)
        else:
            results.sort(key=lambda item: item.ranking_score, reverse=True)
        return results[:limit]

    def get_commander_profile(self, name: str) -> CommanderProfile | None:
        card = self.get_card(name)
        if not card or not self.is_legal_commander(card):
            return None

        archetypes = self.commander_archetypes_for_name(card.name)
        if archetypes:
            best = sorted(
                archetypes,
                key=lambda archetype: (
                    archetype.source_count,
                    archetype.metadata.commander_package.support_depth if archetype.metadata.commander_package else 0,
                ),
                reverse=True,
            )[0]
            package = best.metadata.commander_package
            tags = list(dict.fromkeys(best.tags + card.tags))
            return CommanderProfile(
                card=card,
                strategy_summary=best.strategy,
                colors=best.colors or list(card.color_identity or card.colors),
                tags=tags,
                popularity=float(best.source_count),
                support_depth=package.support_depth if package else best.source_count,
                package_richness=self._package_richness_from_package(package),
                average_lands=package.average_lands if package else None,
                average_ramp=package.average_ramp if package else None,
                average_draw=package.average_draw if package else None,
                average_interaction=package.average_interaction if package else None,
                signature_cards=package.signature_cards if package else best.metadata.core_cards[:8],
                synergy_packages=package.synergy_packages if package else best.metadata.flex_cards[:8],
                ramp_package=package.ramp_package if package else self._fallback_packages("ramp", tags),
                draw_package=package.draw_package if package else self._fallback_packages("draw", tags),
                interaction_package=package.interaction_package if package else self._fallback_packages("interaction", tags),
                land_package=package.land_package if package else best.metadata.land_packages[:8],
                related_archetypes=[archetype.name for archetype in archetypes[:5]],
            )

        fallback_tags = list(dict.fromkeys(card.tags + self._infer_commander_tags(card)))
        commander_colors = list(card.color_identity or card.colors)
        return CommanderProfile(
            card=card,
            strategy_summary=self._fallback_commander_strategy(card, fallback_tags),
            colors=commander_colors,
            tags=fallback_tags,
            popularity=0,
            support_depth=len(self._support_cards_for_tags(fallback_tags, commander_colors)),
            package_richness=sum(
                len(self._fallback_packages(role, fallback_tags))
                for role in ("ramp", "draw", "interaction")
            ),
            average_lands=37,
            average_ramp=10,
            average_draw=10,
            average_interaction=10,
            signature_cards=self._fallback_packages("engine", fallback_tags),
            synergy_packages=self._fallback_packages("engine", fallback_tags),
            ramp_package=self._fallback_packages("ramp", fallback_tags),
            draw_package=self._fallback_packages("draw", fallback_tags),
            interaction_package=self._fallback_packages("interaction", fallback_tags),
            land_package=self._fallback_land_package(commander_colors),
            related_archetypes=[],
        )

    def card_packages_by_role_theme(
        self,
        *,
        format_name: str,
        role: str,
        theme_tags: list[str] | None = None,
        limit: int = 12,
    ) -> list[dict[str, object]]:
        requested_tags = {self._normalize_name(tag) for tag in (theme_tags or [])}
        package_weights: dict[str, dict[str, object]] = {}
        for archetype in self.archetypes_for_format(format_name):
            packages = (
                archetype.metadata.commander_package.ramp_package
                if role == "ramp" and archetype.metadata.commander_package
                else archetype.metadata.commander_package.draw_package
                if role == "draw" and archetype.metadata.commander_package
                else archetype.metadata.commander_package.interaction_package
                if role == "interaction" and archetype.metadata.commander_package
                else archetype.metadata.core_cards + archetype.metadata.flex_cards
            )
            for package in packages:
                # Theme tags are a preference, not a hard filter: role packages
                # (ramp/draw/interaction) only carry role tags, so a hard
                # intersection with theme tags like "tribal" would always come
                # back empty. Matching packages get a weight boost instead.
                theme_match = bool(
                    requested_tags & {self._normalize_name(tag) for tag in package.tags}
                )
                current = package_weights.setdefault(
                    package.name,
                    {"name": package.name, "weight": 0.0, "tags": set(), "average_quantity": package.average_quantity},
                )
                base_weight = (package.inclusion_rate or 0.0) * max(1, archetype.source_count)
                current["weight"] += base_weight * (2.0 if theme_match else 1.0)
                current["tags"].update(package.tags)
        ordered = sorted(package_weights.values(), key=lambda item: item["weight"], reverse=True)
        return [
            {
                "name": item["name"],
                "weight": round(float(item["weight"]), 3),
                "tags": sorted(item["tags"]),
                "average_quantity": item["average_quantity"],
            }
            for item in ordered[:limit]
        ]

    def all_cards(self) -> list[CardRecord]:
        return self._all_cards_cache

    def list_cards_for_format(self, format_name: str) -> list[CardRecord]:
        """Return format-legal, non-joke cards eligible for the optimizer
        pool. Wraps `all_cards()` with the same filters used by the deck
        generator's pool query — `legalities[format] == legal/restricted`
        and `set_type` not in the funny/memorabilia/alchemy blocklist.
        """
        blocked_set_types = {"funny", "memorabilia", "alchemy"}
        legal = {"legal", "restricted"}
        out: list[CardRecord] = []
        for card in self._all_cards_cache:
            if card.legalities.get(format_name, "not_legal") not in legal:
                continue
            if card.set_type and card.set_type in blocked_set_types:
                continue
            out.append(card)
        return out

    def is_legal_commander(self, card: CardRecord) -> bool:
        if card.legalities.get("commander", "not_legal") != "legal":
            return False
        if "Legendary" not in card.type_line:
            return False
        return "Creature" in card.type_line or "Planeswalker" in card.type_line

    def get_card(self, name: str) -> CardRecord | None:
        normalized = self._normalize_name(name)
        card = self._cards_by_name.get(normalized)
        if card is not None:
            self._maybe_enqueue_refresh(card)
        return card

    def _maybe_enqueue_refresh(self, card: CardRecord) -> None:
        """Ask the (optional) refresh service to background-fix suspect cards.

        Wrapped in a broad try/except because the refresh layer is best-effort
        — a failure here must never break the read path.
        """
        service = self.refresh_service
        if service is None:
            return
        try:
            if service.is_suspect(card.set_code):  # type: ignore[attr-defined]
                service.enqueue(self._normalize_name(card.name))  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            logger.debug("Refresh enqueue failed for %s", card.name, exc_info=True)

    def update_cached_image(
        self,
        normalized_name: str,
        *,
        set_code: str,
        image_uri: str | None,
        image_uris: dict[str, str],
        faces: list[dict[str, object]],
    ) -> None:
        """Apply an image refresh to the in-memory card cache.

        Called by the refresh worker after writing the canonical printing to
        the DB. Mutates the existing CardRecord in place so any other handle
        in flight observes the new image too.
        """
        card = self._cards_by_name.get(normalized_name)
        if card is None:
            return
        card.set_code = set_code
        card.image_uri = image_uri
        card.image_uris = image_uris
        card.faces = [CardFaceRecord.model_validate(face) for face in faces]

    def get_cards(self, names: list[str]) -> list[CardRecord]:
        return [card for name in names if (card := self.get_card(name))]

    def search_cards(
        self,
        *,
        query: str,
        format_name: str | None = None,
        limit: int = 12,
    ) -> list[CardSearchResult]:
        normalized_query = self._normalize_name(query)
        if not normalized_query:
            return []
        results: list[tuple[int, CardRecord]] = []
        for card in self.all_cards():
            if format_name and card.legalities.get(format_name, "not_legal") not in {"legal", "restricted"}:
                continue
            normalized_name = self._normalize_name(card.name)
            if normalized_query == normalized_name:
                score = 100
            elif normalized_name.startswith(normalized_query):
                score = 80
            elif normalized_query in normalized_name:
                score = 60
            elif normalized_query in self._normalize_name(card.type_line):
                score = 30
            else:
                continue
            if "Token" in card.type_line:
                score -= 20
            results.append((score, card))
        results.sort(key=lambda item: (-item[0], len(item[1].name), item[1].name))
        return [
            CardSearchResult(
                name=card.name,
                type_line=card.type_line,
                mana_cost=card.mana_cost,
                image_uri=card.image_uri or next((face.image_uri for face in card.faces if face.image_uri), None),
                colors=card.colors,
                color_identity=card.color_identity,
                tags=card.tags,
            )
            for _, card in results[:limit]
        ]

    def nearest_archetypes_for_deck(
        self,
        *,
        format_name: str,
        mainboard: list[CardRef],
        commander: str | None = None,
        limit: int = 3,
    ) -> list[tuple[ArchetypeRecord, float]]:
        requested_names = {self._normalize_name(ref.name) for ref in mainboard if ref.quantity > 0}
        if commander:
            exact = self.commander_archetypes_for_name(commander)
            if exact:
                return [(archetype, 1.0) for archetype in exact[:limit]]
        scored: list[tuple[float, float, ArchetypeRecord]] = []
        for archetype in self.archetypes_for_format(format_name):
            archetype_names = {self._normalize_name(ref.name) for ref in archetype.mainboard if ref.quantity > 0}
            if not archetype_names:
                continue
            overlap = len(requested_names & archetype_names)
            union = len(requested_names | archetype_names)
            jaccard = overlap / union if union else 0.0
            jaccard += min(0.15, len(requested_names & {self._normalize_name(tag) for tag in archetype.tags}) * 0.03)
            # Rank by source_count-weighted score; return raw jaccard as confidence
            rank_score = jaccard * math.log1p(max(1, archetype.source_count))
            scored.append((rank_score, jaccard, archetype))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [(archetype, round(jaccard, 3)) for _, jaccard, archetype in scored[:limit] if jaccard > 0]

    def compare_deck_to_archetype(
        self,
        *,
        mainboard: list[CardRef],
        archetype: ArchetypeRecord,
    ) -> dict[str, list[str]]:
        requested_names = [self._normalize_name(ref.name) for ref in mainboard if ref.quantity > 0]
        archetype_names = [self._normalize_name(ref.name) for ref in archetype.mainboard if ref.quantity > 0]
        requested_set = set(requested_names)
        archetype_set = set(archetype_names)
        overlap = requested_set & archetype_set
        missing = [
            ref.name
            for ref in archetype.mainboard
            if self._normalize_name(ref.name) not in overlap
        ][:8]
        off_plan = [
            ref.name
            for ref in mainboard
            if self._normalize_name(ref.name) not in archetype_set
        ][:8]
        overlap_names = [
            ref.name
            for ref in archetype.mainboard
            if self._normalize_name(ref.name) in overlap
        ][:8]
        return {
            "overlap_cards": overlap_names,
            "missing_cards": missing,
            "off_plan_cards": off_plan,
        }

    def recommend_cards_for_role(
        self,
        *,
        format_name: str,
        role: str,
        colors: list[str] | None = None,
        commander: str | None = None,
        theme_tags: list[str] | None = None,
        exclude_names: list[str] | None = None,
        preferred_names: list[str] | None = None,
        limit: int = 8,
    ) -> list[dict[str, object]]:
        requested_tags = {self._normalize_name(tag) for tag in (theme_tags or []) if tag}
        preferred = {self._normalize_name(name) for name in (preferred_names or []) if name}
        excluded = {self._normalize_name(name) for name in (exclude_names or []) if name}
        commander_colors = set(colors or [])
        commander_card = self.get_card(commander) if commander else None
        if commander_card:
            commander_colors = set(commander_card.color_identity or commander_card.colors)

        results: list[dict[str, object]] = []
        for card in self.all_cards():
            normalized_name = self._normalize_name(card.name)
            if normalized_name in excluded:
                continue
            if "Land" in card.type_line:
                continue
            legality = card.legalities.get(format_name, "not_legal")
            if legality not in {"legal", "restricted"}:
                continue
            if format_name == "commander" and commander_colors and not self._matches_color_identity(card, commander_colors):
                continue
            if format_name != "commander" and colors and not self._color_request_matches(card.color_identity or card.colors, colors):
                continue

            normalized_tags = {self._normalize_name(tag) for tag in card.tags}
            score = 0.0
            reasons: list[str] = []
            role_hints = self.ROLE_HINTS.get(role, {self._normalize_name(role)})
            role_overlap = len(role_hints & normalized_tags)
            if role_overlap:
                score += role_overlap * 10
                reasons.append(f"matches the deck's {role} gap")
            if requested_tags:
                theme_overlap = len(requested_tags & normalized_tags)
                if theme_overlap:
                    score += theme_overlap * 6
                    reasons.append("fits the deck's strongest theme tags")
            if normalized_name in preferred:
                score += 18
                reasons.append("shows up in the nearest shell")
            if "Legendary" in card.type_line and format_name != "commander":
                score -= 2
            if role in {"interaction", "draw", "ramp"} and card.mana_value <= 3:
                score += 4
                reasons.append("helps on the early turns")
            if role == "threat" and 1 <= card.mana_value <= 4:
                score += 3
            if role == "engine" and requested_tags and requested_tags & normalized_tags:
                score += 3
            if score <= 0:
                continue
            results.append(
                {
                    "name": card.name,
                    "score": round(score, 2),
                    "tags": sorted(normalized_tags),
                    "reasons": reasons,
                    "mana_value": card.mana_value,
                }
            )

        results.sort(
            key=lambda item: (
                float(item["score"]),
                -float(item["mana_value"]) if role == "threat" else -min(float(item["mana_value"]), 3),
                item["name"],
            ),
            reverse=True,
        )
        return results[:limit]

    def data_status(self) -> DataStatusResponse:
        # Use already-cached data; infer source by comparing count against sample baseline
        sample_card_count = len(self._sample_cards)
        sample_archetype_count = len(self._sample_archetypes)
        card_count = len(self._all_cards_cache)
        archetype_count = len(self._all_archetypes_cache)
        card_source = "database" if card_count > sample_card_count else "sample"
        archetype_source = "database" if archetype_count > sample_archetype_count else "sample"

        return DataStatusResponse(
            card_source=card_source,
            card_count=card_count,
            archetype_source=archetype_source,
            archetype_count=archetype_count,
            database_url=DATABASE_URL,
            scryfall_ingested=card_source == "database" and card_count > 1000,
        )

    def _fallback_packages(self, role: str, tags: list[str]) -> list[ArchetypePackage]:
        packages = self.card_packages_by_role_theme(format_name="commander", role=role, theme_tags=tags, limit=8)
        return [
            ArchetypePackage(
                name=item["name"],
                inclusion_rate=float(item["weight"]) if isinstance(item["weight"], (int, float)) else None,
                average_quantity=item.get("average_quantity"),
                tags=list(item.get("tags", [])),
            )
            for item in packages
        ]

    def _fallback_land_package(self, colors: list[str]) -> list[ArchetypePackage]:
        """Return basic-land packages restricted to the commander's color identity.

        Off-color basics belong to a different commander identity, so this filter
        is load-bearing — tested by `test_eris_commander_excludes_off_color_basics`.
        """
        basics_by_color = {"W": "Plains", "U": "Island", "B": "Swamp", "R": "Mountain", "G": "Forest"}
        identity = {color for color in colors if color and color != self.COLORLESS_SYMBOL}
        if not identity:
            return [ArchetypePackage(name="Wastes", inclusion_rate=1.0, average_quantity=7, tags=["land"])] if self.get_card("Wastes") else []
        packages: list[ArchetypePackage] = []
        for color in colors:
            land_name = basics_by_color.get(color)
            if not land_name:
                continue
            card = self.get_card(land_name)
            if not card:
                continue
            packages.append(ArchetypePackage(name=land_name, inclusion_rate=1.0, average_quantity=7, tags=["land"]))
        return packages[:5]

    def _support_cards_for_tags(self, tags: list[str], colors: list[str]) -> list[CardRecord]:
        requested_tags = {self._normalize_name(tag) for tag in tags}
        commander_colors = set(colors)
        cards: list[CardRecord] = []
        for card in self.all_cards():
            if not self._matches_color_identity(card, commander_colors):
                continue
            if requested_tags & {self._normalize_name(tag) for tag in card.tags}:
                cards.append(card)
        return cards

    def _matches_color_identity(self, card: CardRecord, commander_colors: set[str]) -> bool:
        identity = set(card.color_identity or card.colors)
        return not identity or identity.issubset(commander_colors)

    def infer_deck_colors(self, names: list[str], commander: str | None = None) -> list[str]:
        if commander:
            commander_card = self.get_card(commander)
            if commander_card:
                return list(commander_card.color_identity or commander_card.colors)
        colors: set[str] = set()
        for card in self.get_cards(names):
            colors.update(card.color_identity or card.colors)
        return sorted(colors)

    def _fallback_commander_strategy(self, card: CardRecord, tags: list[str]) -> str:
        if tags:
            return f"{card.name} is treated as a commander-focused {' / '.join(tags[:3])} shell using corpus-derived support packages."
        return f"{card.name} is treated as a commander-focused midrange shell using legal cards from its color identity."

    def _infer_commander_tags(self, card: CardRecord) -> list[str]:
        inferred = list(card.tags)
        oracle_text = card.oracle_text.lower()
        if "draw" in oracle_text:
            inferred.append("draw")
        if "create" in oracle_text and "token" in oracle_text:
            inferred.append("tokens")
        if "life" in oracle_text:
            inferred.append("lifegain")
        if "graveyard" in oracle_text:
            inferred.append("graveyard")
        if "cast" in oracle_text and "instant" in oracle_text:
            inferred.append("spells")
        return list(dict.fromkeys(inferred))

    @staticmethod
    def _package_richness_from_package(package: object) -> int:
        if package is None:
            return 0
        return sum(
            len(getattr(package, field))
            for field in ("signature_cards", "synergy_packages", "ramp_package", "draw_package", "interaction_package")
        )

    @staticmethod
    def _to_card_record(row: Card) -> CardRecord:
        links = CardPurchaseLinks.model_validate(row.purchase_links or {})
        links.amazon_search = ensure_affiliate_tag(links.amazon_search, row.name)
        return CardRecord(
            oracle_id=row.oracle_id,
            scryfall_id=row.scryfall_id,
            name=row.name,
            normalized_name=row.normalized_name,
            mana_cost=row.mana_cost,
            mana_value=row.mana_value,
            colors=row.colors,
            color_identity=row.color_identity,
            type_line=row.type_line,
            oracle_text=row.oracle_text,
            keywords=row.keywords,
            layout=row.layout,
            rarity=row.rarity,
            set_code=row.set_code,
            set_type=row.set_type,
            released_at=row.released_at,
            image_uri=row.image_uri,
            image_uris=row.image_uris,
            faces=[CardFaceRecord.model_validate(face) for face in row.card_faces],
            legalities=row.legalities,
            price_usd=row.price_usd,
            price_usd_foil=row.price_usd_foil,
            tags=row.tags,
            purchase_links=links,
        )

    @staticmethod
    def _to_archetype_record(row: Archetype) -> ArchetypeRecord:
        return ArchetypeRecord(
            id=row.id,
            name=row.name,
            format=row.format,
            colors=row.colors,
            tags=row.tags,
            strategy=row.strategy,
            commander=row.commander,
            mainboard=[CardRef.model_validate(item) for item in row.mainboard],
            sideboard=[CardRef.model_validate(item) for item in row.sideboard],
            source_count=row.source_count,
            avg_placement=row.avg_placement,
            metadata=ArchetypeMetadata.model_validate(row.metadata_json or {}),
        )
