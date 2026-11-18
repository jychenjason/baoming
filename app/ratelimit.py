"""In-memory sliding-window limiter for repeated failures."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class FailureLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str) -> deque[float] | None:
        failures = self._failures.get(key)
        if not failures:
            return None
        cutoff = self.clock() - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            self._failures.pop(key, None)
            return None
        return failures

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            failures = self._prune(key)
            return failures is not None and len(failures) >= self.limit

    def record_failure(self, key: str) -> None:
        with self._lock:
            failures = self._prune(key)
            if failures is None:
                failures = self._failures.setdefault(key, deque())
            failures.append(self.clock())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


LOGIN_FAILURE_LIMIT = 5
