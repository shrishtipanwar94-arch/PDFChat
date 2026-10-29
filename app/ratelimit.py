"""In-memory sliding-window rate limiter, keyed by session ID.

Good enough for a single process; several workers would need a shared store.
"""

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry = int(self.window - (now - hits[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests. Please slow down.",
                    headers={"Retry-After": str(retry)},
                )
            hits.append(now)
            if len(self._hits) > 10_000:
                self._prune(now)

    def _prune(self, now: float) -> None:
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window]:
            del self._hits[key]
