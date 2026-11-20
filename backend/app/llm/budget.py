"""Hourly budget for live model calls (MAX_LIVE_LLM_CALLS_PER_HOUR). Cache hits don't count."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

from .base import BudgetExceededError

WINDOW_S = 3600.0


class CallBudget:
    def __init__(self, limit_per_hour: int, now: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit_per_hour
        self._now = now
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def _trim(self, t: float) -> None:
        while self._calls and t - self._calls[0] >= WINDOW_S:
            self._calls.popleft()

    def remaining(self) -> int:
        with self._lock:
            self._trim(self._now())
            return max(0, self.limit - len(self._calls))

    def acquire(self) -> None:
        """Record one live call, or raise BudgetExceededError when the hour's budget is used."""
        with self._lock:
            t = self._now()
            self._trim(t)
            if len(self._calls) >= self.limit:
                raise BudgetExceededError(
                    f"The live reading limit ({self.limit} per hour) has been reached. "
                    "Cached results are still available; try again later."
                )
            self._calls.append(t)


_budgets: dict[int, CallBudget] = {}
_budgets_lock = threading.Lock()


def get_budget(limit_per_hour: int) -> CallBudget:
    with _budgets_lock:
        if limit_per_hour not in _budgets:
            _budgets[limit_per_hour] = CallBudget(limit_per_hour)
        return _budgets[limit_per_hour]
