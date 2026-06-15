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
        self._calls_since_sweep = 0

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
            # Periodically drop keys whose window has fully expired so the
            # dict doesn't grow unbounded with one entry per client IP.
            self._calls_since_sweep += 1
            if self._calls_since_sweep >= 1024:
                self._calls_since_sweep = 0
                stale = [k for k, ts in self._timestamps.items() if not ts or ts[-1] <= cutoff]
                for k in stale:
                    del self._timestamps[k]
            return True


# 30 deck generations per IP per minute is generous for interactive use
# while blocking automated abuse.
deck_rate_limiter = InMemoryRateLimiter(requests_per_minute=30)

# The prose endpoint fans out to an LLM and is markedly more expensive
# (latency + cost) than the deterministic endpoints, so it gets a
# tighter budget.
prose_rate_limiter = InMemoryRateLimiter(requests_per_minute=10)

# Deck evaluation runs several hundred simulated games; keep it bounded.
evaluate_rate_limiter = InMemoryRateLimiter(requests_per_minute=20)
