"""Lazy, rate-limited background refresh of stale or suspect card rows.

The bulk Scryfall ingest seeds the card index once. Some printings selected
during that ingest are non-English (e.g. `soa`, `pwcs`, `ptk`) and surface in
the UI as foreign-art images. Re-running the bulk ingest works but is heavy.
This service is the lighter alternative:

1. `CardRepository.get_card` calls `enqueue_if_stale(card)` after returning a
   row. If the card's set is in `SUSPECT_SETS`, the name is added to a queue.
2. A background daemon thread drains the queue at <= 8 req/sec, hits
   Scryfall's `/cards/named?exact=NAME` endpoint, and rewrites the row with
   the canonical English printing's image / set / faces.
3. After the DB write, the service updates the repository's in-memory
   `_cards_by_name` cache so subsequent `get_card` calls return the fresh
   record without paying another DB read.

The service never blocks request handling. The first request that surfaces a
foreign card returns the stale data; the second (after the worker has
processed the queue) returns the canonical English image.
"""
from __future__ import annotations

import logging
import threading
import time
from queue import Empty, Queue
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import update

from app.config import SCRYFALL_USER_AGENT
from app.db import session_scope
from app.db_models import Card

if TYPE_CHECKING:  # pragma: no cover
    from app.services.card_repository import CardRepository

logger = logging.getLogger(__name__)


# Sets known to ship non-English / regional-art printings whose image looks
# foreign even though Scryfall stores the oracle entry as English. Anything
# matching here will be enqueued for refresh on first surface.
SUSPECT_SETS: frozenset[str] = frozenset(
    {
        "ptk",   # Portal Three Kingdoms (Chinese-only printing)
        "pwcs",  # World Championship Promos (regional, foreign-text)
        "soa",   # Secrets of Strixhaven Mystical Archive (Japanese)
        "ren",   # Renaissance (German / Italian)
        "rin",   # Rinascimento (Italian)
        "fbb",   # Foreign Black Border
        "fwb",   # Foreign White Border
        "4bb",   # 4th Edition Black Border (Japanese)
        "ja22",  # Jumpstart 2022 Japanese
        "wc97", "wc98", "wc99", "wc00", "wc01", "wc02", "wc03", "wc04",
    }
)


class CardRefreshService:
    """Drains a queue of card names and refreshes their DB rows from Scryfall.

    Designed to be a singleton owned by the FastAPI app. Call `start()` once
    on app startup and `stop()` on shutdown. `enqueue(name)` is non-blocking
    and idempotent within a process lifetime.
    """

    SCRYFALL_NAMED_URL = "https://api.scryfall.com/cards/named"

    def __init__(
        self,
        repository: "CardRepository",
        *,
        rate_limit_delay_sec: float = 0.13,  # ~7.7 req/sec, under Scryfall's 10/sec ceiling
        max_queue: int = 4096,
    ) -> None:
        self.repository = repository
        self.rate_limit_delay_sec = rate_limit_delay_sec
        self._queue: Queue[str] = Queue(maxsize=max_queue)
        self._enqueued: set[str] = set()
        self._enqueued_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._client: httpx.Client | None = None

    # ── Public API ────────────────────────────────────────────────────────

    def is_suspect(self, set_code: str | None) -> bool:
        if not set_code:
            return False
        return set_code.lower() in SUSPECT_SETS

    def enqueue(self, normalized_name: str) -> None:
        """Add a card name to the refresh queue if not already queued.

        Silently no-ops if the queue is full (we are already saturated and
        the request handler should not block on this side-effect).
        """
        if not normalized_name:
            return
        with self._enqueued_lock:
            if normalized_name in self._enqueued:
                return
            self._enqueued.add(normalized_name)
        try:
            self._queue.put_nowait(normalized_name)
        except Exception:
            with self._enqueued_lock:
                self._enqueued.discard(normalized_name)

    def start(self) -> None:
        if self._worker and self._worker.is_alive():
            return
        self._stop_event.clear()
        self._client = httpx.Client(
            timeout=20.0,
            headers={"User-Agent": SCRYFALL_USER_AGENT, "Accept": "application/json"},
        )
        self._worker = threading.Thread(target=self._run, name="card-refresh", daemon=True)
        self._worker.start()
        logger.info("CardRefreshService started")

    def stop(self, timeout: float = 2.0) -> None:
        self._stop_event.set()
        if self._worker:
            self._worker.join(timeout=timeout)
            self._worker = None
        if self._client:
            self._client.close()
            self._client = None
        logger.info("CardRefreshService stopped")

    # ── Internals ─────────────────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                normalized_name = self._queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                self._refresh_one(normalized_name)
            except Exception:  # pragma: no cover — defensive: never let the worker die
                logger.exception("card-refresh worker error for %s", normalized_name)
            finally:
                self._queue.task_done()
                # Even on failure, leave the name in `_enqueued` to avoid
                # busy-looping on cards that consistently fail to refresh.
                time.sleep(self.rate_limit_delay_sec)

    def _refresh_one(self, normalized_name: str) -> None:
        card = self.repository.get_card(normalized_name)
        if not card:
            return
        if not self.is_suspect(card.set_code):
            return  # Some other thread may have refreshed already.
        client = self._client
        if client is None:
            return
        response = client.get(self.SCRYFALL_NAMED_URL, params={"exact": card.name})
        if response.status_code == 429:
            # Yield aggressively and let the next loop pick it up again.
            time.sleep(1.0)
            with self._enqueued_lock:
                self._enqueued.discard(normalized_name)
            self.enqueue(normalized_name)
            return
        if response.status_code == 404:
            return
        if response.status_code != 200:
            logger.warning("Scryfall refresh %s -> %d", card.name, response.status_code)
            return
        payload = response.json()
        if str(payload.get("lang") or "en") != "en":
            return
        old_set = card.set_code or ""
        new_set = str(payload.get("set") or old_set)
        if new_set.lower() == old_set.lower():
            return  # Scryfall returned the same printing — nothing to do.
        image_uris_raw = payload.get("image_uris") or {}
        face_records = self._build_faces(payload)
        primary = (
            image_uris_raw.get("large")
            or image_uris_raw.get("normal")
            or image_uris_raw.get("small")
            or next((face["image_uri"] for face in face_records if face.get("image_uri")), None)
        )
        image_uris = {k: v for k, v in image_uris_raw.items() if v}

        with session_scope() as session:
            session.execute(
                update(Card)
                .where(Card.normalized_name == card.normalized_name)
                .values(
                    set_code=new_set,
                    image_uri=primary,
                    image_uris=image_uris,
                    card_faces=face_records,
                )
            )
        # Also update the repository's in-memory cache so the next call to
        # get_card returns the canonical English printing without re-reading
        # from disk.
        self.repository.update_cached_image(
            card.normalized_name,
            set_code=new_set,
            image_uri=primary,
            image_uris=image_uris,
            faces=face_records,
        )
        logger.info("Refreshed card image %s: %s -> %s", card.name, old_set, new_set)

    @staticmethod
    def _build_faces(payload: dict) -> list[dict]:
        faces: list[dict] = []
        for face in payload.get("card_faces") or []:
            face_image_uris = face.get("image_uris") or {}
            faces.append(
                {
                    "name": face.get("name"),
                    "mana_cost": face.get("mana_cost") or "",
                    "type_line": face.get("type_line") or "",
                    "oracle_text": face.get("oracle_text") or "",
                    "image_uri": (
                        face_image_uris.get("large")
                        or face_image_uris.get("normal")
                        or face_image_uris.get("small")
                    ),
                }
            )
        return faces
