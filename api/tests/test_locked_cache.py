"""locked_cached_property builds each value once under concurrent first access."""

from __future__ import annotations

import threading
import time

from app.services.locked_cache import locked_cached_property


class _Slow:
    def __init__(self) -> None:
        self.builds = 0

    @locked_cached_property
    def value(self) -> list[int]:
        self.builds += 1
        time.sleep(0.05)  # widen the race window
        return [self.builds]

    @locked_cached_property
    def derived(self) -> int:
        return self.value[0] * 10  # nested access must not deadlock


def test_concurrent_first_access_builds_once() -> None:
    obj = _Slow()
    results: list[list[int]] = []
    threads = [threading.Thread(target=lambda: results.append(obj.value)) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert obj.builds == 1
    assert all(result is results[0] for result in results)


def test_nested_cached_properties() -> None:
    obj = _Slow()
    assert obj.derived == 10
    assert obj.builds == 1
