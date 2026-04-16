from __future__ import annotations

import json
from functools import cached_property

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select

from app.config import ARCHETYPE_PATH, CARD_CACHE_PATH
from app.db import session_scope
from app.db_models import Archetype, Card
from app.models import ArchetypeMetadata, ArchetypeRecord, CardRecord, CardRef


class CardRepository:
    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(name.lower().split())

    @cached_property
    def _sample_cards(self) -> dict[str, CardRecord]:
        with CARD_CACHE_PATH.open() as handle:
            raw_cards = json.load(handle)
        cards: dict[str, CardRecord] = {}
        for item in raw_cards:
            record = CardRecord.model_validate(item)
            cards[self._normalize_name(record.name)] = record
        return cards

    @cached_property
    def _sample_archetypes(self) -> list[ArchetypeRecord]:
        with ARCHETYPE_PATH.open() as handle:
            raw_archetypes = json.load(handle)
        return [ArchetypeRecord.model_validate(item) for item in raw_archetypes]

    def all_archetypes(self) -> list[ArchetypeRecord]:
        try:
            with session_scope() as session:
                rows = session.scalars(select(Archetype).order_by(Archetype.format, Archetype.name)).all()
            if rows:
                return [self._to_archetype_record(row) for row in rows]
        except (SQLAlchemyError, ModuleNotFoundError):
            pass
        return sorted(self._sample_archetypes, key=lambda row: (row.format, row.name))

    def archetypes_for_format(self, format_name: str) -> list[ArchetypeRecord]:
        try:
            with session_scope() as session:
                rows = session.scalars(
                    select(Archetype).where(Archetype.format == format_name).order_by(Archetype.name)
                ).all()
            if rows:
                return [self._to_archetype_record(row) for row in rows]
        except (SQLAlchemyError, ModuleNotFoundError):
            pass
        return [row for row in self._sample_archetypes if row.format == format_name]

    def all_cards(self) -> list[CardRecord]:
        try:
            with session_scope() as session:
                rows = session.scalars(select(Card).order_by(Card.name)).all()
            if rows:
                return [self._to_card_record(row) for row in rows]
        except (SQLAlchemyError, ModuleNotFoundError):
            pass
        return sorted(self._sample_cards.values(), key=lambda card: card.name)

    def get_card(self, name: str) -> CardRecord | None:
        normalized_name = self._normalize_name(name)
        try:
            with session_scope() as session:
                row = session.scalar(select(Card).where(Card.normalized_name == normalized_name))
            if row:
                return self._to_card_record(row)
        except (SQLAlchemyError, ModuleNotFoundError):
            pass
        return self._sample_cards.get(normalized_name)

    def get_cards(self, names: list[str]) -> list[CardRecord]:
        return [card for name in names if (card := self.get_card(name))]

    @staticmethod
    def _to_card_record(row: Card) -> CardRecord:
        return CardRecord(
            oracle_id=row.oracle_id,
            name=row.name,
            mana_cost=row.mana_cost,
            mana_value=row.mana_value,
            colors=row.colors,
            color_identity=row.color_identity,
            type_line=row.type_line,
            oracle_text=row.oracle_text,
            set_code=row.set_code,
            released_at=row.released_at,
            image_uri=row.image_uri,
            legalities=row.legalities,
            price_usd=row.price_usd,
            tags=row.tags,
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
