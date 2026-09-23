import threading
import time

class SlidingWindowLimiter:

    def __init__(self, max_calls: int, window_seconds: int):
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _fresh(self, key: str, now: float) -> list:
        hits = [t for t in self._hits.get(key, []) if now - t < self.window_seconds]
        self._hits[key] = hits
        return hits

    def check_and_record(self, *keys: str) -> int:
        now = time.time()
        with self._lock:
            worst = 0
            for key in keys:
                hits = self._fresh(key, now)
                if len(hits) >= self.max_calls:
                    wait = int(self.window_seconds - (now - hits[0])) + 1
                    worst = max(worst, wait)
            if worst:
                return worst
            for key in keys:
                self._hits[key].append(now)
        return 0

class RateLimiter:

    def __init__(self, max_failures: int=8, window_seconds: int=900):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _fresh(self, key: str, now: float) -> list:
        hits = [t for t in self._hits.get(key, []) if now - t < self.window_seconds]
        if hits:
            self._hits[key] = hits
        else:
            self._hits.pop(key, None)
        return hits

    def retry_after(self, *keys: str, now: float | None=None) -> int:
        now = time.time() if now is None else now
        worst = 0
        with self._lock:
            for key in keys:
                hits = self._fresh(key, now)
                if len(hits) >= self.max_failures:
                    worst = max(worst, int(self.window_seconds - (now - hits[0])) + 1)
        return worst

    def record_failure(self, *keys: str, now: float | None=None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            for key in keys:
                self._hits.setdefault(key, []).append(now)

    def clear(self, *keys: str) -> None:
        with self._lock:
            for key in keys:
                self._hits.pop(key, None)