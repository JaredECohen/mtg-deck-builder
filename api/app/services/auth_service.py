"""Optional email magic-link sign-in.

The deck lab stays usable with no account. A signed-in user gets a personal
library (owner ``user:<id>``) that the shared server API key cannot read.

Sessions and magic links are opaque random tokens. Only their sha256 hashes
are stored, so a database read does not yield a usable credential. Logout
deletes the session row, which revokes the cookie immediately.

Mail is sent through Resend when ``RESEND_API_KEY`` and ``AUTH_FROM_EMAIL``
are set. ``MTG_AUTH_DEBUG=1`` includes the link in the API response for local
development and tests. Leave that unset in production.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from app.db_models import AuthSession, Base, LoginToken, UserAccount

logger = logging.getLogger(__name__)

_ready_engines: set[int] = set()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,200}$")

LOGIN_TTL = timedelta(minutes=20)
SESSION_TTL = timedelta(days=30)
_USER_PREFIX = "user:"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def auth_debug_enabled() -> bool:
    return os.getenv("MTG_AUTH_DEBUG", "").lower() in {"1", "true", "yes"}


def public_site_url() -> str:
    raw = os.getenv("MTG_PUBLIC_SITE_URL", "https://mtgdecklab.app").strip().rstrip("/")
    if not raw.startswith(("https://", "http://")):
        return "https://mtgdecklab.app"
    return raw


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not local or not domain:
        return "***"
    return f"{local[:1]}***@{domain}"


def normalize_email(value: str) -> str | None:
    email = value.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return None
    return email


def _ensure_schema(engine) -> None:
    if id(engine) in _ready_engines:
        return
    Base.metadata.create_all(
        engine,
        tables=[UserAccount.__table__, LoginToken.__table__, AuthSession.__table__],
    )
    _ready_engines.add(id(engine))


class AuthService:
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

    def request_magic_link(self, email: str) -> dict:
        """Create a one-time link for ``email``. Always call this only after
        the route has decided the request is allowed (rate limit, valid address)."""
        self._ensure()
        token = secrets.token_urlsafe(32)
        now = _now()
        row = LoginToken(
            id=uuid.uuid4().hex,
            email=email,
            token_hash=_hash_token(token),
            expires_at=_iso(now + LOGIN_TTL),
            used_at=None,
        )
        session = self._session()
        try:
            session.add(row)
            session.commit()
        finally:
            session.close()
        url = f"{public_site_url()}/auth/verify?token={token}"
        _send_magic_link(email, url)
        body: dict = {"ok": True}
        if auth_debug_enabled():
            body["debug_url"] = url
        return body

    def verify(self, token: str) -> dict | None:
        """Consume a magic link and mint a session. None when the token is
        missing, expired, or already used."""
        if not token or not _TOKEN_RE.match(token):
            return None
        self._ensure()
        now = _now()
        session = self._session()
        try:
            row = session.query(LoginToken).filter(LoginToken.token_hash == _hash_token(token)).first()
            if row is None or row.used_at is not None or _parse(row.expires_at) <= now:
                return None
            # Claim the link with a conditional update so two requests racing on
            # the same token cannot both mint a session.
            claimed = (
                session.query(LoginToken)
                .filter(LoginToken.id == row.id, LoginToken.used_at.is_(None))
                .update({LoginToken.used_at: _iso(now)}, synchronize_session=False)
            )
            if claimed != 1:
                session.rollback()
                return None
            user = session.query(UserAccount).filter(UserAccount.email == row.email).first()
            if user is None:
                user = UserAccount(id=uuid.uuid4().hex, email=row.email, created_at=_iso(now))
                session.add(user)
            raw_session = secrets.token_urlsafe(32)
            session.add(
                AuthSession(
                    id=uuid.uuid4().hex,
                    user_id=user.id,
                    token_hash=_hash_token(raw_session),
                    expires_at=_iso(now + SESSION_TTL),
                    created_at=_iso(now),
                )
            )
            session.commit()
            return {"session_token": raw_session, "user": {"id": user.id, "email": user.email}}
        finally:
            session.close()

    def user_for_session(self, token: str | None) -> dict | None:
        if not token or not _TOKEN_RE.match(token):
            return None
        self._ensure()
        session = self._session()
        try:
            row = session.query(AuthSession).filter(AuthSession.token_hash == _hash_token(token)).first()
            if row is None or _parse(row.expires_at) <= _now():
                return None
            user = session.get(UserAccount, row.user_id)
            if user is None:
                return None
            return {"id": user.id, "email": user.email}
        finally:
            session.close()

    def owner_for_session(self, token: str | None) -> str | None:
        user = self.user_for_session(token)
        if user is None:
            return None
        return _USER_PREFIX + user["id"]

    def revoke(self, token: str | None) -> None:
        if not token or not _TOKEN_RE.match(token):
            return
        self._ensure()
        session = self._session()
        try:
            row = session.query(AuthSession).filter(AuthSession.token_hash == _hash_token(token)).first()
            if row is not None:
                session.delete(row)
                session.commit()
        finally:
            session.close()

    def delete_user(self, user_id: str) -> None:
        """Remove the account, its sessions, and unused magic links for that email."""
        self._ensure()
        session = self._session()
        try:
            user = session.get(UserAccount, user_id)
            if user is None:
                return
            session.query(AuthSession).filter(AuthSession.user_id == user_id).delete()
            session.query(LoginToken).filter(LoginToken.email == user.email).delete()
            session.delete(user)
            session.commit()
        finally:
            session.close()


def _send_magic_link(email: str, url: str) -> None:
    """Best-effort mail. Failures are logged without the link or the API key."""
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_addr = os.getenv("AUTH_FROM_EMAIL", "").strip()
    if not api_key or not from_addr:
        logger.error(
            "magic link not sent to %s: set RESEND_API_KEY and AUTH_FROM_EMAIL",
            mask_email(email),
        )
        return
    payload = {
        "from": from_addr,
        "to": [email],
        "subject": "Your MTG Deck Lab sign-in link",
        "text": (
            "Sign in to MTG Deck Lab:\n\n"
            f"{url}\n\n"
            "This link expires in 20 minutes and works once. "
            "If you didn't ask for it, you can ignore this email.\n"
        ),
    }
    request = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "mtg-deck-lab",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        logger.warning("magic link email failed for %s", mask_email(email))


auth_service = AuthService()


def owner_for_session(token: str | None) -> str | None:
    """Look up the module-level service so tests can replace it."""
    return auth_service.owner_for_session(token)
