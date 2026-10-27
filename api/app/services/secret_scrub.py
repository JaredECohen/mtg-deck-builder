"""Strip secrets out of anything that can be stored on a deck or returned.

Shared deck pages are public. A caller must not be able to stash an API key,
a session token, or a provider key in a deck name, note, or evaluation blob
and have the share endpoint echo it back.
"""

from __future__ import annotations

import os

_REDACTED = "[redacted]"
# Minimum length avoids wiping ordinary words that happen to match a short env value.
_MIN_SECRET_LEN = 8

# Dict keys that are never deck content. Compared case-insensitively after
# dashes are folded to underscores. Values under these keys are dropped, not
# redacted, so the key name itself is not a clue that a secret was present.
_SENSITIVE_KEYS = {
    "owner",
    "api_key",
    "apikey",
    "x_api_key",
    "authorization",
    "password",
    "secret",
    "session",
    "session_token",
    "token",
    "access_token",
    "refresh_token",
    "resend_api_key",
    "anthropic_api_key",
    "openai_api_key",
    "mtg_api_key",
    "cookie",
    "set_cookie",
    "email",
}

_SECRET_ENVS = (
    "MTG_API_KEY",
    "RESEND_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
)


def env_secrets() -> list[str]:
    """Secret values currently in the process environment. Never cached."""
    found: list[str] = []
    for name in _SECRET_ENVS:
        raw = os.getenv(name, "")
        parts = raw.split(",") if name == "MTG_API_KEY" else [raw]
        for part in parts:
            secret = part.strip()
            if len(secret) >= _MIN_SECRET_LEN:
                found.append(secret)
    found.sort(key=len, reverse=True)
    return found


def _normalize_key(key: object) -> str:
    return str(key).strip().lower().replace("-", "_")


def scrub_secrets(value: object, extra: list[str] | None = None) -> object:
    """Return a copy of ``value`` with secrets removed.

    ``extra`` covers request-scoped secrets that are not in the environment,
    such as the caller's session token.
    """
    secrets = list(env_secrets())
    for item in extra or []:
        if isinstance(item, str) and len(item) >= _MIN_SECRET_LEN and item not in secrets:
            secrets.append(item)
    secrets.sort(key=len, reverse=True)
    return _scrub(value, secrets)


def _redact(text: str, secrets: list[str]) -> str:
    redacted = text
    for secret in secrets:
        if secret in redacted:
            redacted = redacted.replace(secret, _REDACTED)
    return redacted


def _scrub(value: object, secrets: list[str]) -> object:
    if isinstance(value, str):
        return _redact(value, secrets)
    if isinstance(value, list):
        return [_scrub(item, secrets) for item in value]
    if isinstance(value, dict):
        cleaned: dict[object, object] = {}
        for key, item in value.items():
            if _normalize_key(key) in _SENSITIVE_KEYS:
                continue
            cleaned[key] = _scrub(item, secrets)
        return cleaned
    return value
