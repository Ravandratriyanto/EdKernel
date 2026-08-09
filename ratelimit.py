"""A small in-memory failure counter, used to slow down login guessing.

Deliberately not a general rate limiter. It counts *failures* only, so a student
typing their own password correctly fifty times is never slowed down, and a
guesser is stopped after a handful of misses.

Limits worth knowing before trusting it:

- **In memory.** Restarting the server clears every counter.
- **One process.** Two workers keep two separate counts, so the real limit is
  the configured one times the number of workers.

Both are fine for one Flask process on localhost, which is what this is. Behind
a real deployment with several workers, this needs to move to the database or
to a shared cache.
"""

import threading
import time


class RateLimiter:
    """Blocks a key once it collects `max_failures` inside `window_seconds`.

    The window slides: failures are forgotten once they are older than the
    window, so a blocked key frees itself without any cleanup task.
    """

    def __init__(self, max_failures: int = 8, window_seconds: int = 900):
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _fresh(self, key: str, now: float) -> list:
        """Failures for one key with the expired ones dropped. Caller holds the lock."""
        hits = [t for t in self._hits.get(key, []) if now - t < self.window_seconds]
        if hits:
            self._hits[key] = hits
        else:
            # Do not keep an empty list around: this dict is only ever pruned
            # by being read, so an untouched key would otherwise leak forever.
            self._hits.pop(key, None)
        return hits

    def retry_after(self, *keys: str, now: float | None = None) -> int:
        """Seconds until the caller may try again, or 0 if it may try now.

        Several keys are checked at once — typically the IP and the username —
        and the longest wait wins. Blocking on username as well as IP is what
        stops a spread-out attack on one account from a fresh address each time.
        """
        now = time.time() if now is None else now
        worst = 0
        with self._lock:
            for key in keys:
                hits = self._fresh(key, now)
                if len(hits) >= self.max_failures:
                    # The block lifts when the oldest failure leaves the window.
                    worst = max(worst, int(self.window_seconds - (now - hits[0])) + 1)
        return worst

    def record_failure(self, *keys: str, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            for key in keys:
                self._hits.setdefault(key, []).append(now)

    def clear(self, *keys: str) -> None:
        """Forget a key's failures — called after a successful login."""
        with self._lock:
            for key in keys:
                self._hits.pop(key, None)
