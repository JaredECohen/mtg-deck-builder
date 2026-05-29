"""Persistent deck history + sharing.

Backed by the ``saved_decks`` table (SQLite by default, Postgres in
prod). The schema is created lazily on first use so the feature works
without a separate migration step in dev. ``owner`` is an opaque string
(e.g. the API key or a future user id) so this slots into a real
multi-user workspace later without a data migration.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from app.db_models import Base, SavedDeck

# Track which engines have had the schema created (keyed by id) so the
# lazy create_all runs once per engine — not once globally, which would
# skip table creation for a second engine (e.g. an isolated test DB).
_ready_engines: set[int] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_schema(engine) -> None:
    if id(engine) not in _ready_engines:
        Base.metadata.create_all(engine, tables=[SavedDeck.__table__])
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
            "owner": row.owner,
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

    def get(self, deck_id: str) -> dict | None:
        self._ensure()
        session = self._session()
        try:
            row = session.get(SavedDeck, deck_id)
            return self._to_dict(row) if row else None
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
