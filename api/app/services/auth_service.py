"""Optional email magic-link sign-in.

The deck lab stays usable with no account. A signed-in user gets a personal
library (owner ``user:<id>``) that the shared server API key cannot read.

Sessions and magic links are opaque random tokens. Only their sha256 hashes
are stored, so a database read does not yield a usable credential. Logout
deletes the session row, which revokes the cookie immediately.

A magic link is bound to a pre-auth cookie set when the link was requested.
``verify`` consumes the link only when that cookie matches, and each login
mints a new session id. Asking for a new link invalidates older unused ones.

Mail is sent through Resend when ``RESEND_API_KEY`` and ``AUTH_FROM_EMAIL``
are set. ``MTG_AUTH_DEBUG=1`` includes the link in the API response for local
development and tests. That flag is ignored when ``FLY_APP_NAME`` is set or
``ENV=production``.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import inspect, text
from sqlalchemy.orm import sessionmaker

from app.db_models import AuthRateBucket, AuthSession, Base, LoginToken, UserAccount

logger = logging.getLogger(__name__)

_last_purge_at = 0.0
_PURGE_EVERY_SECONDS = 3600

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,200}$")

LOGIN_TTL = timedelta(minutes=20)
SESSION_TTL = timedelta(days=30)
EMAIL_LIMIT = 5
EMAIL_DAILY_LIMIT = 10
IP_LIMIT = 20
# Ten addresses at this daily cap stay under the default 200/day global cap.
IP_DAILY_LIMIT = 15
_USER_PREFIX = "user:"
PREAUTH_MISMATCH = "preauth_mismatch"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hour_window(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H")


def _day_window(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d")


def valid_preauth(value: str | None) -> bool:
    return bool(value and _TOKEN_RE.match(value))


def _is_production() -> bool:
    if os.getenv("FLY_APP_NAME", "").strip():
        return True
    return os.getenv("ENV", "").strip().lower() == "production"


def auth_debug_enabled() -> bool:
    """True only outside production. FLY_APP_NAME or ENV=production hard-refuses the flag."""
    if _is_production():
        return False
    return os.getenv("MTG_AUTH_DEBUG", "").lower() in {"1", "true", "yes"}


def log_auth_debug_configuration() -> None:
    """Startup log. Loud when the flag is set, and an error when production ignores it."""
    flag = os.getenv("MTG_AUTH_DEBUG", "").strip().lower()
    if flag not in {"1", "true", "yes"}:
        return
    if _is_production():
        logger.error(
            "MTG_AUTH_DEBUG is set but refused because FLY_APP_NAME is set or ENV=production. "
            "Magic-link URLs will not be included in API responses."
        )
        return
    logger.warning(
        "MTG_AUTH_DEBUG is enabled. Magic-link URLs are included in API responses. "
        "Never set this when FLY_APP_NAME is set or ENV=production."
    )


def daily_email_cap() -> int:
    raw = os.getenv("MTG_AUTH_DAILY_EMAIL_CAP", "200").strip()
    try:
        value = int(raw)
    except ValueError:
        return 200
    if value < 1:
        return 200
    return min(value, 100_000)


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


def _ensure_login_token_columns(engine) -> None:
    inspector = inspect(engine)
    if not inspector.has_table(LoginToken.__tablename__):
        return
    columns = {col["name"] for col in inspector.get_columns(LoginToken.__tablename__)}
    if "preauth_hash" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE login_tokens ADD COLUMN preauth_hash VARCHAR(64)"))


def _ensure_schema(engine) -> None:
    """Create auth tables if they are missing.

    Do not remember engines by ``id(engine)``. CPython reuses that id after the
    engine is collected, and the next empty database would skip ``CREATE TABLE``.
    ``create_all`` is ``CREATE TABLE IF NOT EXISTS`` plus a column check.
    """
    Base.metadata.create_all(
        engine,
        tables=[
            UserAccount.__table__,
            LoginToken.__table__,
            AuthSession.__table__,
            AuthRateBucket.__table__,
        ],
    )
    _ensure_login_token_columns(engine)


def rate_limit_ip(value: str | None) -> str:
    """Identity used for the per-IP sign-in budget.

    IPv6 is grouped by /64 so a single network cannot rotate hosts to escape
    the cap. IPv4-mapped IPv6 is counted as the embedded IPv4 address.
    """
    raw = (value or "").strip()
    if not raw:
        return "unknown"
    try:
        parsed = ipaddress.ip_address(raw)
    except ValueError:
        return raw
    if isinstance(parsed, ipaddress.IPv6Address):
        mapped = parsed.ipv4_mapped
        if mapped is not None:
            return str(mapped)
        prefix = ipaddress.IPv6Network((parsed, 64), strict=False).network_address
        return f"{prefix}/64"
    return str(parsed)


def _bump(session, bucket: str, window: str, limit: int) -> bool:
    """Atomic fixed-window increment. False when this window is already full."""
    row = session.execute(
        text(
            "INSERT INTO auth_rate_buckets (bucket, window_start, count) "
            "VALUES (:bucket, :window, 1) "
            "ON CONFLICT(bucket) DO UPDATE SET "
            "count = CASE WHEN auth_rate_buckets.window_start != :window "
            "THEN 1 ELSE auth_rate_buckets.count + 1 END, "
            "window_start = :window "
            "WHERE auth_rate_buckets.window_start != :window "
            "OR auth_rate_buckets.count < :limit "
            "RETURNING count"
        ),
        {"bucket": bucket, "window": window, "limit": limit},
    ).first()
    return row is not None


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

    def _purge(self, session, now: datetime) -> None:
        cutoff = _iso(now)
        session.execute(
            text("DELETE FROM login_tokens WHERE used_at IS NOT NULL OR expires_at <= :cutoff"),
            {"cutoff": cutoff},
        )
        session.execute(
            text("DELETE FROM auth_sessions WHERE expires_at <= :cutoff"),
            {"cutoff": cutoff},
        )
        old_day = (now - timedelta(days=2)).strftime("%Y-%m-%d")
        session.execute(
            text("DELETE FROM auth_rate_buckets WHERE window_start < :cutoff"),
            {"cutoff": old_day},
        )

    def _maybe_purge(self, session) -> None:
        global _last_purge_at
        now_m = time.monotonic()
        if _last_purge_at and now_m - _last_purge_at < _PURGE_EVERY_SECONDS:
            return
        self._purge(session, _now())
        _last_purge_at = now_m

    def purge_expired(self) -> None:
        """Delete used or expired magic links, expired sessions, and old rate buckets."""
        self._ensure()
        session = self._session()
        try:
            self._purge(session, _now())
            session.commit()
        finally:
            session.close()

    def consume_ip(self, client_ip: str) -> bool:
        """Persist the per-IP hour and day budgets. False when either is exhausted."""
        self._ensure()
        session = self._session()
        try:
            self._maybe_purge(session)
            identity = _hash_token(rate_limit_ip(client_ip))
            now = _now()
            allowed = [
                _bump(session, "ip:" + identity, _hour_window(now), IP_LIMIT),
                _bump(session, "ip-day:" + identity, _day_window(now), IP_DAILY_LIMIT),
            ]
            if not all(allowed):
                session.rollback()
                return False
            session.commit()
            return True
        finally:
            session.close()

    def consume_email_send(self, email: str) -> bool:
        """Persist per-email hour and day budgets plus the global daily cap.

        A refusal rolls back every counter touched by this call. It does not
        touch login tokens; a throttled request must leave a pending link in place.
        """
        self._ensure()
        now = _now()
        session = self._session()
        try:
            email_hash = _hash_token(email)
            allowed = [
                _bump(session, "email:" + email_hash, _hour_window(now), EMAIL_LIMIT),
                _bump(session, "email-day:" + email_hash, _day_window(now), EMAIL_DAILY_LIMIT),
                _bump(session, "global-email", _day_window(now), daily_email_cap()),
            ]
            if not all(allowed):
                session.rollback()
                return False
            session.commit()
            return True
        finally:
            session.close()

    def request_magic_link(self, email: str, preauth: str) -> dict:
        """Create a one-time link for ``email`` bound to ``preauth``.

        Older unused links for this address are deleted in the same transaction.
        Call this only after the route has allowed the request (rate limit, valid address).
        """
        if not valid_preauth(preauth):
            raise ValueError("preauth")
        self._ensure()
        token = secrets.token_urlsafe(32)
        now = _now()
        session = self._session()
        try:
            self._maybe_purge(session)
            session.query(LoginToken).filter(
                LoginToken.email == email,
                LoginToken.used_at.is_(None),
            ).delete(synchronize_session=False)
            session.add(
                LoginToken(
                    id=uuid.uuid4().hex,
                    email=email,
                    token_hash=_hash_token(token),
                    preauth_hash=_hash_token(preauth),
                    expires_at=_iso(now + LOGIN_TTL),
                    used_at=None,
                )
            )
            session.commit()
        finally:
            session.close()
        url = f"{public_site_url()}/auth/verify?token={token}"
        _send_magic_link(email, url)
        body: dict = {"ok": True}
        if auth_debug_enabled():
            body["debug_url"] = url
        return body

    def verify(
        self,
        token: str,
        preauth: str | None = None,
        previous_session: str | None = None,
    ) -> dict | str | None:
        """Consume a magic link and mint a new session id.

        Returns a session payload, ``preauth_mismatch`` when the link is live
        but the pre-auth cookie does not match (the link is not consumed), or
        None when the token is missing, expired, or already used.
        """
        if not token or not _TOKEN_RE.match(token):
            return None
        self._ensure()
        now = _now()
        session = self._session()
        try:
            self._maybe_purge(session)
            row = session.query(LoginToken).filter(LoginToken.token_hash == _hash_token(token)).first()
            if row is None or row.used_at is not None or _parse(row.expires_at) <= now:
                session.commit()
                return None
            presented = _hash_token(preauth) if valid_preauth(preauth) else ""
            stored = row.preauth_hash or ""
            if (
                not presented
                or not stored
                or len(presented) != len(stored)
                or not hmac.compare_digest(presented, stored)
            ):
                session.commit()
                return PREAUTH_MISMATCH
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
            if previous_session and _TOKEN_RE.match(previous_session):
                session.query(AuthSession).filter(
                    AuthSession.token_hash == _hash_token(previous_session)
                ).delete(synchronize_session=False)
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
            "Sign in to MTG Deck Lab. Open this link in the same browser where you requested it, "
            "then press Sign in. Opening the link does not sign you in by itself.\n\n"
            f"{url}\n\n"
            "This link expires in 20 minutes and works once. "
            "If you open it on another device, request a new link there. "
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
