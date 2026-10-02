"""
Login throttling — blunts password brute-forcing.

Deliberately in-process and dependency-free: it holds a small dict of
recent failures per key (email + client IP). That is the right trade-off
for a single-worker deployment and costs nothing to run.

LIMITATION, stated plainly: the counters live in memory, so they reset on
restart and are NOT shared between uvicorn workers or servers. If you scale
past one worker, move this to Redis — the function signatures here won't
need to change.
"""
import time
from collections import defaultdict
from threading import Lock

# key -> list of failure timestamps
_failures: dict[str, list[float]] = defaultdict(list)
_lock = Lock()

MAX_ATTEMPTS = 8          # failures allowed inside the window
WINDOW_SECONDS = 300      # 5 minutes
LOCKOUT_SECONDS = 900     # 15 minutes once the limit is hit


def _prune(key: str, now: float) -> list[float]:
    recent = [t for t in _failures[key] if now - t < WINDOW_SECONDS]
    _failures[key] = recent
    return recent


def seconds_until_unblocked(key: str) -> int:
    """0 if the caller may try again, else how long they must wait."""
    now = time.time()
    with _lock:
        recent = _prune(key, now)
        if len(recent) < MAX_ATTEMPTS:
            return 0
        unblock_at = recent[-1] + LOCKOUT_SECONDS
        return max(0, int(unblock_at - now))


def record_failure(key: str) -> None:
    with _lock:
        now = time.time()
        _prune(key, now)
        _failures[key].append(now)


def reset(key: str) -> None:
    """Clear the counter after a successful login."""
    with _lock:
        _failures.pop(key, None)
