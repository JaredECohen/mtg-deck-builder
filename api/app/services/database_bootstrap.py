from __future__ import annotations

from sqlalchemy import inspect

from app.db import get_engine
from app.db_models import Base


def create_schema() -> None:
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    _ensure_tournament_deck_columns(engine)


def _ensure_tournament_deck_columns(engine) -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    if "tournament_decks" not in existing_tables:
        return

    existing_columns = {column["name"] for column in inspector.get_columns("tournament_decks")}
    column_sql = {
        "dedupe_key": "ALTER TABLE tournament_decks ADD COLUMN dedupe_key VARCHAR(255)",
        "source_url": "ALTER TABLE tournament_decks ADD COLUMN source_url TEXT",
        "format_season": "ALTER TABLE tournament_decks ADD COLUMN format_season VARCHAR(64)",
        "event_tier": "ALTER TABLE tournament_decks ADD COLUMN event_tier VARCHAR(64)",
        "event_size": "ALTER TABLE tournament_decks ADD COLUMN event_size INTEGER",
        "finish_label": "ALTER TABLE tournament_decks ADD COLUMN finish_label VARCHAR(64)",
        "confidence": "ALTER TABLE tournament_decks ADD COLUMN confidence FLOAT",
    }

    with engine.begin() as connection:
        for column_name, ddl in column_sql.items():
            if column_name in existing_columns:
                continue
            connection.exec_driver_sql(ddl)
