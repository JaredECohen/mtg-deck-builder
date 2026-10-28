"""Persistent deck history + sharing.

Backed by the ``saved_decks`` table (SQLite by default, Postgres in
prod). The schema is created lazily on first use so the feature works
without a separate migration step in dev. ``owner`` is an opaque string:

* ``key:`` + a hash of an API key (direct API clients, and anonymous saves
  made through the site's server key)
* ``user:`` + an account id (personal library; see ``auth_service``)

``owner`` never leaves the service: callers get ``_to_dict`` output, which
omits it. Raw API keys are never stored — see ``owner_id``. User-owned rows
are not rewritten by the raw-key hashing pass.

Public share pages read a snapshot (list, mana curve, per-card notes, colors,
price, key cards) so the page does not need to rebuild the deck. ``visibility``
is ``public`` (indexable, listed for the sitemap) or ``unlisted`` (link works,
omitted from the sitemap so the site can send noindex).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import inspect, or_, text
from sqlalchemy.orm import sessionmaker

from app.db_models import Base, SavedDeck
from app.services.secret_scrub import scrub_secrets

# Track which engines have had the schema created (keyed by id) so the
# lazy create_all runs once per engine — not once globally, which would
# skip table creation for a second engine (e.g. an isolated test DB).
_ready_engines: set[int] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


logger = logging.getLogger(__name__)

_KEY_PREFIX = "key:"
_USER_PREFIX = "user:"
_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{20,200}$")

_COLORS = ("W", "U", "B", "R", "G", "C")
_CARD_TYPES = {
    "Creature",
    "Planeswalker",
    "Instant",
    "Sorcery",
    "Enchantment",
    "Artifact",
    "Battle",
    "Land",
    "Other",
}

# Columns added after the table first shipped. create_all does not alter an
# existing table, so an in-place install adds these on startup.
_ADDED_COLUMNS = {
    "visibility": "VARCHAR(16) NOT NULL DEFAULT 'public'",
    "colors": "JSON",
    "price_usd": "FLOAT",
    "card_notes": "JSON",
    "mana_curve": "JSON",
    "card_types": "JSON",
    "key_cards": "JSON",
    "edit_secret_hash": "VARCHAR(64)",
}


def _edit_secret_matches(stored: str | None, presented: str | None) -> bool:
    """Constant-time check of a per-deck edit secret. Legacy rows have no hash."""
    if not stored or not presented or not _SECRET_RE.match(presented):
        return False
    digest = hashlib.sha256(presented.encode("utf-8")).hexdigest()
    if len(digest) != len(stored):
        return False
    return hmac.compare_digest(digest, stored)


def owner_id(api_key: str | None) -> str | None:
    """Opaque, stable owner id for an API key. The key itself is never stored."""
    if api_key is None:
        return None
    return _KEY_PREFIX + hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:24]


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
    """Rows saved before owners were hashed hold the raw API key. Replace it.

    ``key:`` hashes and ``user:`` account ids are already opaque and are left
    alone. Hashing a ``user:`` id would orphan that person's library.
    """
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT id, owner FROM saved_decks WHERE owner IS NOT NULL "
                "AND owner NOT LIKE :key_prefix AND owner NOT LIKE :user_prefix"
            ),
            {"key_prefix": _KEY_PREFIX + "%", "user_prefix": _USER_PREFIX + "%"},
        ).all()
        for row_id, raw_owner in rows:
            conn.execute(
                text("UPDATE saved_decks SET owner = :owner WHERE id = :id"),
                {"owner": owner_id(raw_owner), "id": row_id},
            )
    if rows:
        logger.warning("Hashed %d saved-deck owner(s) that held a raw API key", len(rows))


def _ensure_saved_deck_columns(engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table(SavedDeck.__tablename__):
        return
    existing = {col["name"] for col in inspector.get_columns(SavedDeck.__tablename__)}
    missing = {name: ddl for name, ddl in _ADDED_COLUMNS.items() if name not in existing}
    index_names = {index["name"] for index in inspector.get_indexes(SavedDeck.__tablename__) if index["name"]}
    with engine.begin() as conn:
        for name, ddl in missing.items():
            conn.execute(text(f"ALTER TABLE saved_decks ADD COLUMN {name} {ddl}"))
        if "visibility" in missing:
            # Rows saved before visibility existed were shared by link only. Their
            # owners never chose to be indexed, so keep them out of the sitemap.
            conn.execute(text("UPDATE saved_decks SET visibility = 'unlisted'"))
        if "ix_saved_decks_visibility" not in index_names and "visibility" in existing | set(missing):
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_saved_decks_visibility ON saved_decks (visibility)"
            ))


def ensure_saved_deck_schema(engine) -> None:
    """Create or migrate ``saved_decks`` on ``engine``. Safe to call twice."""
    if id(engine) in _ready_engines:
        return
    _set_aside_legacy_table(engine)
    Base.metadata.create_all(engine, tables=[SavedDeck.__table__])
    _ensure_saved_deck_columns(engine)
    _hash_raw_owners(engine)
    _ready_engines.add(id(engine))


def _json_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _json_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def clean_colors(colors: list[str] | None) -> list[str]:
    seen: list[str] = []
    for raw in colors or []:
        color = str(raw).strip().upper()
        if color in _COLORS and color not in seen:
            seen.append(color)
    return seen


def clean_key_cards(names: list[str] | None, mainboard: list[dict], card_types: dict) -> list[str]:
    cleaned: list[str] = []
    for raw in names or []:
        name = str(raw).strip()[:200]
        if name and name not in cleaned:
            cleaned.append(name)
        if len(cleaned) >= 8:
            return cleaned
    if cleaned:
        return cleaned
    lands = {name for name, kind in card_types.items() if kind == "Land"}
    for card in mainboard:
        name = str(card.get("name", "")).strip()
        if not name or name in lands or name in cleaned:
            continue
        cleaned.append(name[:200])
        if len(cleaned) >= 4:
            break
    return cleaned


def clean_card_types(card_types: dict | None) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for raw_name, raw_type in (card_types or {}).items():
        name = str(raw_name).strip()[:200]
        kind = str(raw_type).strip()
        if name and kind in _CARD_TYPES and len(cleaned) < 300:
            cleaned[name] = kind
    return cleaned


def _can_access(row: SavedDeck | None, owner: str | None) -> bool:
    """Who may read or change a deck by id.

    User libraries (``user:``) are private to that account even when API-key
    auth is disabled (``owner`` is None). Other rows keep the original rule:
    a None owner means auth is off and the row is reachable, which is how
    single-tenant dev and the existing tests work.
    """
    if row is None:
        return False
    stored = row.owner
    if stored and stored.startswith(_USER_PREFIX):
        return owner == stored
    if owner is not None and stored != owner:
        return False
    return True


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
            ensure_saved_deck_schema(self._session_factory.kw["bind"])
        else:
            from app.db import get_engine
            ensure_saved_deck_schema(get_engine())

    @staticmethod
    def _to_dict(row: SavedDeck) -> dict:
        data = {
            "id": row.id,
            "share_token": row.share_token,
            "name": row.name,
            "format": row.format,
            "commander": row.commander,
            "mainboard": _json_list(row.mainboard),
            "sideboard": _json_list(row.sideboard),
            "notes": row.notes or "",
            "evaluation": _json_dict(row.evaluation),
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "visibility": row.visibility or "public",
            "colors": _json_list(row.colors),
            "price_usd": row.price_usd,
            "card_notes": _json_list(row.card_notes),
            "mana_curve": _json_list(row.mana_curve),
            "card_types": _json_dict(row.card_types),
            "key_cards": _json_list(row.key_cards),
        }
        # Identifiers are generated by us. Restoring them keeps a secret that
        # happened to be a substring of the token from breaking the link.
        share_token = data["share_token"]
        deck_id = data["id"]
        cleaned = scrub_secrets(data)
        if isinstance(cleaned, dict):
            cleaned["id"] = deck_id
            cleaned["share_token"] = share_token
            return cleaned
        return data

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
        visibility: str = "unlisted",
        colors: list[str] | None = None,
        price_usd: float | None = None,
        card_notes: list[dict] | None = None,
        mana_curve: list[dict] | None = None,
        card_types: dict | None = None,
        key_cards: list[str] | None = None,
        secret_values: list[str] | None = None,
    ) -> dict:
        self._ensure()
        now = _now()
        board = [dict(card) for card in mainboard]
        side = [dict(card) for card in (sideboard or [])]
        types = clean_card_types(card_types)
        # Anonymous decks (including the site's shared API key) all share one
        # owner, so the id alone must not be enough to delete them.
        edit_secret = None if (owner or "").startswith(_USER_PREFIX) else secrets.token_urlsafe(32)
        extras = list(secret_values or [])
        if edit_secret:
            extras.append(edit_secret)
        content = scrub_secrets(
            {
                "name": name or "Untitled deck",
                "commander": commander,
                "notes": notes or "",
                "evaluation": evaluation or {},
                "mainboard": board,
                "sideboard": side,
                "colors": clean_colors(colors),
                "card_notes": card_notes or [],
                "mana_curve": mana_curve or [],
                "card_types": types,
                "key_cards": clean_key_cards(key_cards, board, types),
            },
            extra=extras,
        )
        assert isinstance(content, dict)
        if visibility not in {"public", "unlisted"}:
            visibility = "unlisted"
        row = SavedDeck(
            id=uuid.uuid4().hex,
            share_token=secrets.token_urlsafe(12),
            owner=owner,
            name=str(content["name"] or "Untitled deck")[:255],
            format=format_id,
            commander=content["commander"],
            mainboard=content["mainboard"],
            sideboard=content["sideboard"],
            notes=str(content["notes"] or ""),
            evaluation=content["evaluation"] if isinstance(content["evaluation"], dict) else {},
            created_at=now,
            updated_at=now,
            visibility=visibility,
            colors=content["colors"] if isinstance(content["colors"], list) else [],
            price_usd=price_usd,
            card_notes=content["card_notes"] if isinstance(content["card_notes"], list) else [],
            mana_curve=content["mana_curve"] if isinstance(content["mana_curve"], list) else [],
            card_types=content["card_types"] if isinstance(content["card_types"], dict) else {},
            key_cards=content["key_cards"] if isinstance(content["key_cards"], list) else [],
            edit_secret_hash=hashlib.sha256(edit_secret.encode("utf-8")).hexdigest() if edit_secret else None,
        )
        session = self._session()
        try:
            session.add(row)
            session.commit()
            payload = self._to_dict(row)
            # Returned once. Later reads omit it; only the hash is stored.
            if edit_secret:
                payload["edit_secret"] = edit_secret
            return payload
        finally:
            session.close()

    def get(self, deck_id: str, *, owner: str | None = None) -> dict | None:
        self._ensure()
        session = self._session()
        try:
            row = session.get(SavedDeck, deck_id)
            if not _can_access(row, owner):
                return None
            return self._to_dict(row)
        finally:
            session.close()

    def get_by_share_token(self, token: str) -> dict | None:
        self._ensure()
        session = self._session()
        try:
            row = session.query(SavedDeck).filter(SavedDeck.share_token == token).first()
            if row is None:
                return None
            # The id is what rename and delete take. Anonymous decks all belong to
            # the site's API key, so a share link must not hand it out.
            data = self._to_dict(row)
            data.pop("id", None)
            return data
        finally:
            session.close()

    def history(self, *, owner: str | None = None, limit: int = 50) -> list[dict]:
        self._ensure()
        session = self._session()
        try:
            query = session.query(SavedDeck)
            if owner is None:
                # Auth is off. Hide personal libraries; keep anonymous rows and
                # legacy key-owned rows visible, matching single-tenant dev.
                query = query.filter(or_(SavedDeck.owner.is_(None), ~SavedDeck.owner.like(f"{_USER_PREFIX}%")))
            else:
                query = query.filter(SavedDeck.owner == owner)
            rows = query.order_by(SavedDeck.created_at.desc()).limit(limit).all()
            return [self._to_dict(row) for row in rows]
        finally:
            session.close()

    def public_index(self, *, limit: int = 500, offset: int = 0) -> list[dict]:
        """Tokens of indexable decks. No list, notes, owner, or email."""
        self._ensure()
        limit = max(1, min(limit, 2000))
        offset = max(0, offset)
        session = self._session()
        try:
            rows = (
                session.query(SavedDeck.share_token, SavedDeck.updated_at)
                .filter(or_(SavedDeck.visibility == "public", SavedDeck.visibility.is_(None)))
                .order_by(SavedDeck.updated_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [{"share_token": token, "updated_at": updated} for token, updated in rows]
        finally:
            session.close()

    def update(
        self,
        deck_id: str,
        *,
        owner: str | None = None,
        name: str | None = None,
        visibility: str | None = None,
        secret_values: list[str] | None = None,
    ) -> dict | None:
        self._ensure()
        session = self._session()
        try:
            row = session.get(SavedDeck, deck_id)
            if not _can_access(row, owner):
                return None
            assert row is not None
            if name is not None:
                cleaned = scrub_secrets(name, extra=secret_values)
                row.name = (str(cleaned) if isinstance(cleaned, str) else "Untitled deck")[:255] or "Untitled deck"
            if visibility in {"public", "unlisted"}:
                row.visibility = visibility
            row.updated_at = _now()
            session.commit()
            return self._to_dict(row)
        finally:
            session.close()

    def delete(self, deck_id: str, *, owner: str | None = None, edit_secret: str | None = None) -> bool:
        self._ensure()
        session = self._session()
        try:
            row = session.get(SavedDeck, deck_id)
            if not _can_access(row, owner):
                return False
            assert row is not None
            # A signed-in library is proved by the session. Anonymous rows,
            # including ones saved before edit secrets existed, are not.
            if not (row.owner or "").startswith(_USER_PREFIX):
                if not _edit_secret_matches(row.edit_secret_hash, edit_secret):
                    return False
            session.delete(row)
            session.commit()
            return True
        finally:
            session.close()

    def delete_all_for_owner(self, owner: str) -> int:
        """Remove every deck in one personal library. Refuses other owner ids."""
        if not owner.startswith(_USER_PREFIX):
            return 0
        self._ensure()
        session = self._session()
        try:
            rows = session.query(SavedDeck).filter(SavedDeck.owner == owner).all()
            for row in rows:
                session.delete(row)
            session.commit()
            return len(rows)
        finally:
            session.close()
