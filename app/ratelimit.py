"""In-memory sliding-window limiter for repeated failures."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable

DEFAULT_MAX_KEYS = 10_000


class FailureLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = DEFAULT_MAX_KEYS,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self.max_keys = max_keys
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune_key(self, key: str, now: float) -> None:
        failures = self._failures.get(key)
        if failures is None:
            return
        cutoff = now - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()

    def _prune_all(self, now: float) -> None:
        cutoff = now - self.window_seconds
        stale = [
            key
            for key, failures in self._failures.items()
            if not failures or failures[-1] <= cutoff
        ]
        for key in stale:
            self._failures.pop(key, None)

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            now = self.clock()
            self._prune_all(now)
            self._prune_key(key, now)
            failures = self._failures.get(key)
            return bool(failures) and len(failures) >= self.limit

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = self.clock()
            self._prune_all(now)
            self._prune_key(key, now)
            if key not in self._failures and len(self._failures) >= self.max_keys:
                # Bound memory under a spoofed-IP flood; the oldest key goes first.
                self._failures.pop(next(iter(self._failures)), None)
            self._failures[key].append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


LOGIN_FAILURE_LIMIT = 5
