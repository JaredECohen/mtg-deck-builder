from __future__ import annotations

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Card(Base):
    __tablename__ = "cards"

    oracle_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True, unique=True)
    mana_cost: Mapped[str] = mapped_column(String(255), default="")
    mana_value: Mapped[float] = mapped_column(Float, default=0)
    colors: Mapped[list[str]] = mapped_column(JSON, default=list)
    color_identity: Mapped[list[str]] = mapped_column(JSON, default=list)
    type_line: Mapped[str] = mapped_column(String(255))
    oracle_text: Mapped[str] = mapped_column(Text, default="")
    legalities: Mapped[dict[str, str]] = mapped_column(JSON, default=dict)
    price_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    set_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    released_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    image_uri: Mapped[str | None] = mapped_column(Text, nullable=True)


class Archetype(Base):
    __tablename__ = "archetypes"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    format: Mapped[str] = mapped_column(String(32), index=True)
    colors: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    strategy: Mapped[str] = mapped_column(Text)
    commander: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mainboard: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    sideboard: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_placement: Mapped[float | None] = mapped_column(Float, nullable=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column("metadata", JSON, default=dict)


class TournamentDeck(Base):
    __tablename__ = "tournament_decks"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    event_name: Mapped[str] = mapped_column(String(255), index=True)
    event_date: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    format: Mapped[str] = mapped_column(String(32), index=True)
    player_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    placement: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    wins: Mapped[int | None] = mapped_column(Integer, nullable=True)
    losses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    draws: Mapped[int | None] = mapped_column(Integer, nullable=True)
    colors: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    commander: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mainboard: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    sideboard: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    metadata_json: Mapped[dict[str, object]] = mapped_column("metadata", JSON, default=dict)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    records_processed: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
