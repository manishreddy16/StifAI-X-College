"""Small in-process sliding-window limiter (per key). Resets on restart; one limiter per process."""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float, *, clock=time.monotonic, max_keys: int = 10_000):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._max_keys = max_keys
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """Record an attempt; return False if the key is over its limit."""
        now = self._clock()
        with self._lock:
            if len(self._hits) > self._max_keys:
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.window}
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
