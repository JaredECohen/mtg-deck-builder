"""Shared pytest configuration: every test run uses the same card database.

Tests run against ``tests/fixtures/cards.db.gz``, a deterministic ~2k-card cut
of the full Scryfall ingest (plus the full archetype and tournament corpus),
built by ``python -m app.scripts.build_test_fixture``. It is decompressed into
a temporary directory once per session, so tests can write to it (saved decks,
refresh queues) without touching the checked-in file or ``var/``.

Before this, CI ran on the 29-card sample JSON while local runs silently used
the developer's 33k-card ``var/`` DB. Tests needing a real pool were skipped
in CI behind ``MTG_FULL_DATASET``, and tests written against the local DB went
red in CI (main was red from 2026-09-19 to 2026-10-12).

To run the suite against another database, e.g. the full local ingest::

    MTG_TEST_DATABASE_URL=sqlite:///../var/mtg_deck_builder.db python -m pytest

If a new test needs a card the fixture lacks, name it in the test and rebuild
the fixture; the builder picks up every card name that appears as a string
literal under ``app/`` and ``tests/``.
"""

from __future__ import annotations

import atexit
import gzip
import os
import shutil
import tempfile
from pathlib import Path

_FIXTURE = Path(__file__).parent / "fixtures" / "cards.db.gz"


def _use_test_database() -> None:
    # Runs at conftest import, before any test module imports ``app``:
    # app.config reads DATABASE_URL once at import time.
    override = os.getenv("MTG_TEST_DATABASE_URL")
    if override:
        os.environ["DATABASE_URL"] = override
        return
    tmp_dir = Path(tempfile.mkdtemp(prefix="mtg-test-db-"))
    atexit.register(shutil.rmtree, tmp_dir, ignore_errors=True)
    db_path = tmp_dir / "cards.db"
    with gzip.open(_FIXTURE, "rb") as src, open(db_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"


_use_test_database()


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    """Every test starts with empty rate-limit windows. The suite runs dozens
    of generations per minute from one test client, so without this a test
    fails with 429 depending on how many ran before it. Tests that exercise
    limiting still hit the real limit within their own body."""
    from app import rate_limiter

    for limiter in vars(rate_limiter).values():
        if isinstance(limiter, rate_limiter.InMemoryRateLimiter):
            limiter.reset()
    # Same for the whole-response generate cache: a test that patches the
    # generator or validator must not get another test's cached deck.
    import app.main as main_module

    main_module._generate_cache.clear()
    yield
