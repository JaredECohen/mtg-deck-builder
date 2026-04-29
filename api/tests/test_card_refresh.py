"""Unit tests for the lazy card-refresh service.

We exercise enqueue + dedupe + suspect detection without spawning the
background worker thread; the worker's HTTP path is exercised in a separate
focused test that monkey-patches the httpx client.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.card_refresh import SUSPECT_SETS, CardRefreshService


class _StubRepo:
    """Just enough of CardRepository for the service to call into."""

    def __init__(self) -> None:
        self.updates: list[dict] = []

    @staticmethod
    def _normalize_name(name: str) -> str:
        return " ".join(name.lower().split())

    def get_card(self, name: str):  # pragma: no cover — overridden per test
        return None

    def update_cached_image(self, normalized_name, *, set_code, image_uri, image_uris, faces) -> None:
        self.updates.append(
            {
                "normalized_name": normalized_name,
                "set_code": set_code,
                "image_uri": image_uri,
                "image_uris": image_uris,
                "faces": faces,
            }
        )


def test_is_suspect_matches_known_foreign_sets() -> None:
    service = CardRefreshService(_StubRepo())
    for code in ("ptk", "soa", "pwcs", "fbb", "wc97"):
        assert service.is_suspect(code), code
    for code in ("woe", "otj", "mh3", "mom", "neo", "sld", "plst"):
        assert not service.is_suspect(code), code
    assert SUSPECT_SETS  # sanity — never accidentally empty


def test_enqueue_is_idempotent_and_thread_safe() -> None:
    service = CardRefreshService(_StubRepo())
    service.enqueue("monstrous rage")
    service.enqueue("monstrous rage")
    service.enqueue("slickshot show-off")
    # Internal queue size reflects unique entries only.
    assert service._queue.qsize() == 2
    assert service._enqueued == {"monstrous rage", "slickshot show-off"}


def test_enqueue_ignores_empty_name() -> None:
    service = CardRefreshService(_StubRepo())
    service.enqueue("")
    assert service._queue.qsize() == 0


def test_refresh_one_skips_when_card_missing() -> None:
    repo = _StubRepo()
    service = CardRefreshService(repo)
    repo.get_card = lambda name: None  # type: ignore[assignment]
    service._refresh_one("ghost card")
    assert repo.updates == []


def test_refresh_one_skips_when_set_already_canonical() -> None:
    repo = _StubRepo()
    service = CardRefreshService(repo)
    fake_card = MagicMock(name="card")
    fake_card.set_code = "woe"  # not suspect
    repo.get_card = lambda name: fake_card  # type: ignore[assignment]
    service._refresh_one("monstrous rage")
    assert repo.updates == []
