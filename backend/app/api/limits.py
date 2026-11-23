"""Abuse limits on the endpoints that start a run (POST /runs, POST /demo/runs/{id}).

- A token bucket per client address: `RATE_LIMIT_BURST` runs at once, refilled at
  `RATE_LIMIT_RUNS_PER_MINUTE`. Over the limit → 429 `rate_limited` with `Retry-After`.
- A fresh model reading must fit both the client's hourly share
  (`MAX_LIVE_LLM_CALLS_PER_CLIENT_PER_HOUR`) and the global hourly budget; otherwise the upload is
  refused up front with 429 `reading_limit`, before a run is created. Saved readings are free.

State is in memory (one API process, as deployed); a restart resets it.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request

from app.api.deps import APIError
from app.config import get_settings
from app.extract.extractor import needs_live_reading
from app.llm.budget import client_budget, get_budget

IDLE_S = 3600.0  # forget buckets idle this long


@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBuckets:
    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def take(self, key: str, per_minute: float, burst: int) -> float:
        """Take one token for `key`. Returns 0 when allowed, else seconds until one is free."""
        rate = per_minute / 60.0
        with self._lock:
            t = self._now()
            if len(self._buckets) > 10_000:
                self._buckets = {k: b for k, b in self._buckets.items() if t - b.updated < IDLE_S}
            b = self._buckets.get(key)
            if b is None:
                b = self._buckets[key] = _Bucket(float(burst), t)
            b.tokens = min(float(burst), b.tokens + (t - b.updated) * rate)
            b.updated = t
            if b.tokens >= 1:
                b.tokens -= 1
                return 0.0
            return (1 - b.tokens) / rate if rate > 0 else math.inf

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


buckets = TokenBuckets()


def client_key(request: Request) -> str:
    """The caller's address (behind the proxy, uvicorn's --proxy-headers sets it)."""
    return request.client.host if request.client else "unknown"


def limit_run_rate(request: Request) -> str:
    """Dependency for run-creating routes; returns the client key."""
    key = client_key(request)
    s = get_settings()
    if s.rate_limit_runs_per_minute > 0:
        wait = buckets.take(key, s.rate_limit_runs_per_minute, s.rate_limit_burst)
        if wait > 0:
            seconds = max(1, math.ceil(wait))
            raise APIError(
                429,
                "rate_limited",
                f"Too many invoices were sent from this address in a short time. Please wait "
                f"{seconds} second{'s' if seconds != 1 else ''} and try again.",
                headers={"Retry-After": str(seconds)},
            )
    return key


def check_reading_budget(key: str, sha256: str, force_fresh: bool) -> None:
    """Refuse a run up front when it needs a fresh model reading that no budget can cover."""
    s = get_settings()
    if not needs_live_reading(sha256, force_fresh, s):
        return
    if s.max_live_llm_calls_per_client_per_hour > 0:
        mine = client_budget(s.max_live_llm_calls_per_client_per_hour)
        if mine.remaining(key) <= 0:
            raise APIError(
                429,
                "reading_limit",
                f"This address has used its {s.max_live_llm_calls_per_client_per_hour} live "
                "model readings for this hour. Invoices that were read before still work; new "
                "files can be sent again later.",
                headers={"Retry-After": str(int(mine.retry_after(key)) + 1)},
            )
    if get_budget(s.max_live_llm_calls_per_hour).remaining() <= 0:
        raise APIError(
            429,
            "reading_limit",
            "The hourly limit for live model readings has been reached. Invoices that were read "
            "before still work; new files can be sent again later.",
        )
