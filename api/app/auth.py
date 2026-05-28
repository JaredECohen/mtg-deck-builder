"""Optional API-key authentication.

Auth is *opt-in*: when ``MTG_API_KEY`` is unset (local dev, tests) the
dependency is a no-op so nothing breaks. When set, protected endpoints
require a matching ``X-API-Key`` header. Multiple comma-separated keys
are accepted so keys can be rotated without downtime.

This is deliberately simple (shared-secret header) — enough to gate the
expensive LLM-backed endpoints in a single-tenant deployment. A
multi-tenant setup should front this with a real identity provider.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Header, HTTPException


def _valid_keys() -> set[str]:
    raw = os.getenv("MTG_API_KEY", "")
    return {k.strip() for k in raw.split(",") if k.strip()}


def auth_enabled() -> bool:
    return bool(_valid_keys())


def require_api_key(x_api_key: str | None = Header(default=None)) -> str | None:
    """FastAPI dependency. Returns the caller's key (or None when auth is
    disabled). Raises 401 when auth is enabled and the key is missing or
    wrong. Uses a constant-time compare to avoid timing oracles."""
    keys = _valid_keys()
    if not keys:
        return None  # auth disabled
    if x_api_key and any(hmac.compare_digest(x_api_key, k) for k in keys):
        return x_api_key
    raise HTTPException(status_code=401, detail="invalid or missing API key")
