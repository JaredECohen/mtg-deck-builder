from __future__ import annotations

import threading
import time
from collections import defaultdict


class InMemoryRateLimiter:
    """Sliding-window rate limiter backed by an in-process dict.

    Sufficient for single-process deployments.  For multi-process or
    distributed setups replace with a Redis-backed implementation.
    """

    def __init__(self, *, requests_per_minute: int) -> None:
        self.limit = requests_per_minute
        self.window = 60.0
        self._timestamps: defaultdict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._timestamps.clear()

    def is_allowed(self, key: str) -> bool:
        with self._lock:
            now = time.monotonic()
            cutoff = now - self.window
            bucket = self._timestamps[key]
            self._timestamps[key] = [t for t in bucket if t > cutoff]
            if len(self._timestamps[key]) >= self.limit:
                return False
            self._timestamps[key].append(now)
            return True


# 30 deck generations per IP per minute is generous for interactive use
# while blocking automated abuse.
deck_rate_limiter = InMemoryRateLimiter(requests_per_minute=30)
