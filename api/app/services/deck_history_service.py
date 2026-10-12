"""Persistent deck history + sharing.

Backed by the ``saved_decks`` table (SQLite by default, Postgres in
prod). The schema is created lazily on first use so the feature works
without a separate migration step in dev. ``owner`` is an opaque string
(a hashed API key today, a user id later) so this slots into a real
multi-user workspace without a data migration.

``owner`` never leaves the service: callers get ``_to_dict`` output, which
omits it. Raw API keys are never stored — see ``owner_id``.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

from app.db_models import Base, SavedDeck

# Track which engines have had the schema created (keyed by id) so the
# lazy create_all runs once per engine — not once globally, which would
# skip table creation for a second engine (e.g. an isolated test DB).
_ready_engines: set[int] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


logger = logging.getLogger(__name__)

_OWNER_PREFIX = "key:"


def owner_id(api_key: str | None) -> str | None:
    """Opaque, stable owner id for an API key. The key itself is never stored."""
    if api_key is None:
        return None
    return _OWNER_PREFIX + hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:24]


def _set_aside_legacy_table(engine) -> None:
    """The pre-2026-06 deck-lab ``saved_decks`` table (session_id/deck_json/
    chat_history) has the same name but an incompatible schema, and
    ``create_all`` never alters an existing table — every save then 500s.
    Rename it out of the way (data kept) so the current table can be created."""
    inspector = inspect(engine)
    if not inspector.has_table(SavedDeck.__tablename__):
        return
    columns = {col["name"] for col in inspector.get_columns(SavedDeck.__tablename__)}
    if "share_token" in columns:
        return
    legacy_name = f"saved_decks_legacy_{datetime.now(timezone.utc):%Y%m%d%H%M%S}"
    # Index names survive a rename (e.g. ix_saved_decks_format) and would
    # collide with the new table's; drop them from the legacy copy.
    index_names = [index["name"] for index in inspector.get_indexes(SavedDeck.__tablename__) if index["name"]]
    with engine.begin() as conn:
        conn.execute(text(f'ALTER TABLE saved_decks RENAME TO "{legacy_name}"'))
        for name in index_names:
            conn.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
    logger.warning("Renamed legacy saved_decks table to %s", legacy_name)


def _hash_raw_owners(engine) -> None:
    """Rows saved before owners were hashed hold the raw API key. Replace it."""
    with engine.begin() as conn:
        rows = conn.execute(
            text("SELECT id, owner FROM saved_decks WHERE owner IS NOT NULL AND owner NOT LIKE :prefix"),
            {"prefix": _OWNER_PREFIX + "%"},
        ).all()
        for row_id, raw_owner in rows:
            conn.execute(
                text("UPDATE saved_decks SET owner = :owner WHERE id = :id"),
                {"owner": owner_id(raw_owner), "id": row_id},
            )
    if rows:
        logger.warning("Hashed %d saved-deck owner(s) that held a raw API key", len(rows))


def _ensure_schema(engine) -> None:
    if id(engine) not in _ready_engines:
        _set_aside_legacy_table(engine)
        Base.metadata.create_all(engine, tables=[SavedDeck.__table__])
        _hash_raw_owners(engine)
        _ready_engines.add(id(engine))


class DeckHistoryService:
    """CRUD + share for saved decks.

    A ``session_factory`` can be injected for tests; otherwise the
    app-wide one is used.
    """

    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        self._session_factory = session_factory

    def _session(self):
        if self._session_factory is not None:
            return self._session_factory()
        from app.db import _get_session_factory
        return _get_session_factory()()

    def _ensure(self) -> None:
        if self._session_factory is not None:
            _ensure_schema(self._session_factory.kw["bind"])
        else:
            from app.db import get_engine
            _ensure_schema(get_engine())

    @staticmethod
    def _to_dict(row: SavedDeck) -> dict:
        return {
            "id": row.id,
            "share_token": row.share_token,
            "name": row.name,
            "format": row.format,
            "commander": row.commander,
            "mainboard": row.mainboard,
            "sideboard": row.sideboard,
            "notes": row.notes,
            "evaluation": row.evaluation,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    def save(
        self,
        *,
        name: str,
        format_id: str,
        mainboard: list[dict],
        sideboard: list[dict] | None = None,
        commander: str | None = None,
        notes: str = "",
        evaluation: dict | None = None,
        owner: str | None = None,
    ) -> dict:
        self._ensure()
        now = _now()
        row = SavedDeck(
            id=uuid.uuid4().hex,
            share_token=secrets.token_urlsafe(12),
            owner=owner,
            name=name or "Untitled deck",
            format=format_id,
            commander=commander,
            mainboard=[dict(c) for c in mainboard],
            sideboard=[dict(c) for c in (sideboard or [])],
            notes=notes or "",
            evaluation=evaluation or {},
            created_at=now,
            updated_at=now,
        )
        session = self._session()
        try:
            session.add(row)
            session.commit()
            return self._to_dict(row)
        finally:
            session.close()

    def get(self, deck_id: str, *, owner: str | None = None) -> dict | None:
        self._ensure()
        session = self._session()
        try:
            row = session.get(SavedDeck, deck_id)
            if row is None or (owner is not None and row.owner != owner):
                return None
            return self._to_dict(row)
        finally:
            session.close()

    def get_by_share_token(self, token: str) -> dict | None:
        self._ensure()
        session = self._session()
        try:
            row = session.query(SavedDeck).filter(SavedDeck.share_token == token).first()
            return self._to_dict(row) if row else None
        finally:
            session.close()

    def history(self, *, owner: str | None = None, limit: int = 50) -> list[dict]:
        self._ensure()
        session = self._session()
        try:
            query = session.query(SavedDeck)
            if owner is not None:
                query = query.filter(SavedDeck.owner == owner)
            rows = query.order_by(SavedDeck.created_at.desc()).limit(limit).all()
            return [self._to_dict(r) for r in rows]
        finally:
            session.close()

    def delete(self, deck_id: str, *, owner: str | None = None) -> bool:
        self._ensure()
        session = self._session()
        try:
            row = session.get(SavedDeck, deck_id)
            if row is None or (owner is not None and row.owner != owner):
                return False
            session.delete(row)
            session.commit()
            return True
        finally:
            session.close()
