"""Small fixed-window counters. Postgres implements the same operation durably."""

import math
import threading
import time

from .errors import TooManyRequests


class MemoryLimits:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, tuple[int, int]] = {}

    def consume(self, key: str, limit: int, seconds: int) -> None:
        now = time.time()
        expires = (int(now) // seconds + 1) * seconds
        with self._lock:
            if len(self._buckets) >= 10_000:
                self._buckets = {k: v for k, v in self._buckets.items() if v[0] > now}
                if key not in self._buckets and len(self._buckets) >= 10_000:
                    raise TooManyRequests(60)
            previous, used = self._buckets.get(key, (0, 0))
            used = used if previous == expires else 0
            if used >= limit:
                raise TooManyRequests(max(1, math.ceil(expires - now)))
            self._buckets[key] = (expires, used + 1)
