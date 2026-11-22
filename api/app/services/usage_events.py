"""First-party usage events: country, region, and city only.

Writes are server-to-server. ``USAGE_INGEST_SECRET`` must match the
``X-Usage-Ingest-Secret`` header. The comparison is ``hmac.compare_digest``
over equal-length digests. An unset or wrong secret writes nothing.

Rows older than 13 months are deleted on API boot and on a timer. The timer
is not tied to writes. ``MTG_USAGE_PURGE_SCHEDULE=0`` skips the timer (tests);
the boot purge still runs.
"""

from __future__ import annotations

import calendar
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db import get_engine
from app.db_models import Base, UsageEvent
from app.rate_limiter import usage_write_limiter

logger = logging.getLogger(__name__)

USAGE_EVENTS = (
    "page_view",
    "deck_generated",
    "deck_refined",
    "deck_exported",
    "deck_shared",
    "deck_page_viewed",
    "tcgplayer_cart_clicked",
    "guide_viewed",
)
_ALLOWED = frozenset(USAGE_EVENTS)

BODY_MAX = 2048
PATH_MAX = 200
CITY_MAX = 80
REGION_MAX = 64
SECRET_MAX = 1024
RETENTION_MONTHS = 13
_PURGE_INTERVAL_SECONDS = 3600

_HEX_DIGEST = re.compile(r"^[0-9a-fA-F]{32,128}$")
_COORD = re.compile(r"^-?\d{1,3}(?:\.\d+)?\s*,\s*-?\d{1,3}(?:\.\d+)?$")
_COUNTRY = re.compile(r"^[A-Za-z]{2}$")

_schema_ready: set[str] = set()
_scheduler_started = False
_stop = threading.Event()

router = APIRouter()


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def months_ago(moment: datetime, months: int = RETENTION_MONTHS) -> datetime:
    index = moment.month - 1 - months
    year = moment.year + index // 12
    month = index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def retention_cutoff(moment: datetime | None = None) -> str:
    return _stamp(months_ago(moment or datetime.now(timezone.utc)))


def _ip_shaped(value: str) -> bool:
    candidate = value.strip()
    if not candidate or len(candidate) > 128:
        return False
    try:
        ipaddress.ip_address(candidate)
        return True
    except ValueError:
        pass
    if re.fullmatch(r"(?:\d{1,3}\.){3}\d{1,3}", candidate):
        return True
    return bool(candidate.count(":") >= 2 and re.fullmatch(r"[0-9a-fA-F:]+", candidate))


def _sensitive_geo(value: str) -> bool:
    """IP, hashed IP, or a coordinate pair. Those are not a city or region."""
    return _ip_shaped(value) or _HEX_DIGEST.fullmatch(value) is not None or _COORD.fullmatch(value) is not None


def _plain(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text_value = " ".join(value.split())
    if not text_value or _sensitive_geo(text_value):
        return None
    return text_value


def clean_country(value: object) -> str | None:
    text_value = _plain(value)
    if text_value is None or _COUNTRY.fullmatch(text_value) is None:
        return None
    return text_value.upper()


def clean_region(value: object) -> str | None:
    text_value = _plain(value)
    if text_value is None or len(text_value) > REGION_MAX:
        return None
    return text_value


def clean_city(value: object) -> str | None:
    text_value = _plain(value)
    if text_value is None:
        return None
    return text_value[:CITY_MAX]


def clean_path(value: object) -> str | None:
    """Path only. Query, fragment, and ``/d/<token>`` do not get stored."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if "://" in raw[:16]:
        raw = raw.split("://", 1)[1]
        raw = raw.split("/", 1)[1] if "/" in raw else ""
        raw = "/" + raw
    raw = raw.split("#", 1)[0].split("?", 1)[0]
    if not raw.startswith("/"):
        raw = "/" + raw
    if raw == "/d" or raw.startswith("/d/"):
        raw = "/d"
    return raw[:PATH_MAX]


def secret_matches(provided: str | None) -> bool:
    """True only when the header matches USAGE_INGEST_SECRET in constant time.

    Unset secret, missing header, and wrong header are all False. Digests are
    compared so a length difference cannot skip ``compare_digest``.
    """
    expected = os.getenv("USAGE_INGEST_SECRET", "").strip()
    if not expected or not provided or len(provided) > SECRET_MAX:
        return False
    actual = hashlib.sha256(provided.encode("utf-8")).digest()
    wanted = hashlib.sha256(expected.encode("utf-8")).digest()
    return hmac.compare_digest(actual, wanted)


def ensure_schema(engine=None) -> None:
    engine = engine or get_engine()
    key = str(engine.url)
    if key in _schema_ready:
        return
    Base.metadata.create_all(engine, tables=[UsageEvent.__table__])
    _schema_ready.add(key)


def insert_event(
    *,
    event: str,
    path: str,
    country: str | None,
    region: str | None,
    city: str | None,
    created_at: str | None = None,
) -> None:
    engine = get_engine()
    ensure_schema(engine)
    session = sessionmaker(bind=engine, future=True)()
    try:
        session.add(
            UsageEvent(
                created_at=created_at or _stamp(datetime.now(timezone.utc)),
                event=event,
                path=path,
                country=country,
                region=region,
                city=city,
            )
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def purge_expired(now: datetime | None = None) -> int:
    """Delete usage_events older than 13 months. Returns the number removed."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    cutoff = retention_cutoff(moment)
    engine = get_engine()
    ensure_schema(engine)
    with engine.begin() as conn:
        result = conn.execute(
            text("DELETE FROM usage_events WHERE created_at < :cutoff"),
            {"cutoff": cutoff},
        )
        return int(result.rowcount or 0)


def run_retention_loop(interval_seconds: float, stop=None, purge=None) -> None:
    """Call ``purge`` every interval until ``stop`` returns True. No write required."""
    wait = stop or _stop.wait
    run = purge or purge_expired
    while not wait(interval_seconds):
        try:
            run()
        except Exception:
            logger.warning("usage retention purge failed", exc_info=True)


def start_retention_schedule(interval_seconds: float = _PURGE_INTERVAL_SECONDS) -> None:
    """Purge once immediately, then on a timer unless the schedule is disabled."""
    global _scheduler_started
    try:
        purge_expired()
    except Exception:
        logger.warning("usage retention purge on boot failed", exc_info=True)
    if os.getenv("MTG_USAGE_PURGE_SCHEDULE", "1").strip().lower() in {"0", "false", "no"}:
        return
    if _scheduler_started:
        return
    _scheduler_started = True
    threading.Thread(
        target=run_retention_loop,
        args=(interval_seconds,),
        name="usage-retention",
        daemon=True,
    ).start()


def _payload(raw: bytes) -> tuple[str, str, str | None, str | None, str | None]:
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid payload.") from None
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="Invalid payload.")
    event = parsed.get("event")
    if not isinstance(event, str) or event not in _ALLOWED:
        raise HTTPException(status_code=400, detail="Unknown event.")
    path = clean_path(parsed.get("path"))
    if path is None:
        raise HTTPException(status_code=400, detail="A path is required.")
    # Only these three geo fields are read. ip, forwarded-for, lat/long, and
    # postcode keys in the body are ignored and have no column to land in.
    return event, path, clean_country(parsed.get("country")), clean_region(parsed.get("region")), clean_city(parsed.get("city"))


@router.post("/v1/usage", status_code=204)
async def post_usage(request: Request) -> Response:
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > BODY_MAX:
                raise HTTPException(status_code=413, detail="Payload is too large.")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid payload.") from None
    if not secret_matches(request.headers.get("x-usage-ingest-secret")):
        raise HTTPException(status_code=401, detail="Unauthorized.")
    raw = await request.body()
    if len(raw) > BODY_MAX:
        raise HTTPException(status_code=413, detail="Payload is too large.")
    if not usage_write_limiter.is_allowed("usage"):
        raise HTTPException(status_code=429, detail="Too many requests. Please slow down.")
    event, path, country, region, city = _payload(raw)
    try:
        insert_event(event=event, path=path, country=country, region=region, city=city)
    except Exception:
        logger.warning("usage event write failed", exc_info=True)
        raise HTTPException(status_code=500, detail="Usage event was not stored.") from None
    return Response(status_code=204)
