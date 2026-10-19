"""``cached_property`` that computes each value once, even across threads.

Since Python 3.12, ``functools.cached_property`` has no lock. When the warm-up
thread and a request (even a health check) first touch an empty cache at the
same time, both build it. With the 35k-card corpus each copy is hundreds of
MB, and indexes built from the losing copy keep it alive. On Fly's throttled
shared CPU, warm-up took 55–80 s and always overlapped health checks:
uvicorn used 1.85 GB there against 655 MB locally.

One process-wide re-entrant lock serializes the first computation. Cached
properties call each other, so the lock has to be re-entrant, and a single
lock means there is no lock order to get wrong. Once a value is stored, the
lock is never taken again: this is a non-data descriptor, so attribute
lookup finds the instance ``__dict__`` entry first.
"""

from __future__ import annotations

import threading
from functools import cached_property

_LOCK = threading.RLock()


class locked_cached_property(cached_property):  # noqa: N801 - mirrors functools naming
    def __get__(self, instance, owner=None):
        if instance is None:
            return self
        with _LOCK:
            cache = instance.__dict__
            if self.attrname in cache:
                return cache[self.attrname]
            return super().__get__(instance, owner)
