"""Hourly budget for live model calls (MAX_LIVE_LLM_CALLS_PER_HOUR). Cache hits don't count."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

from .base import BudgetExceededError, ClientBudgetExceededError

WINDOW_S = 3600.0


_budgets_lock = threading.Lock()


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


class ClientBudgets:
    """The same hourly window, counted per client (address), so one caller can't use up the
    shared budget by sending new files."""

    def __init__(self, limit_per_hour: int, now: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit_per_hour
        self._now = now
        self._calls: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _trim(self, key: str, t: float) -> deque[float]:
        calls = self._calls.setdefault(key, deque())
        while calls and t - calls[0] >= WINDOW_S:
            calls.popleft()
        return calls

    def remaining(self, key: str) -> int:
        with self._lock:
            return max(0, self.limit - len(self._trim(key, self._now())))

    def retry_after(self, key: str) -> float:
        """Seconds until the client's oldest call in the window expires (0 if under the limit)."""
        with self._lock:
            t = self._now()
            calls = self._trim(key, t)
            if len(calls) < self.limit or not calls:
                return 0.0
            return max(0.0, WINDOW_S - (t - calls[0]))

    def acquire(self, key: str) -> None:
        with self._lock:
            t = self._now()
            calls = self._trim(key, t)
            if len(calls) >= self.limit:
                raise ClientBudgetExceededError(
                    f"This address has used its {self.limit} live model readings for this hour."
                )
            calls.append(t)
            if len(self._calls) > 10_000:
                self._calls = {k: v for k, v in self._calls.items() if v}


_client_budgets: dict[int, ClientBudgets] = {}


def client_budget(limit_per_hour: int) -> ClientBudgets:
    with _budgets_lock:
        if limit_per_hour not in _client_budgets:
            _client_budgets[limit_per_hour] = ClientBudgets(limit_per_hour)
        return _client_budgets[limit_per_hour]


_budgets: dict[int, CallBudget] = {}


def get_budget(limit_per_hour: int) -> CallBudget:
    with _budgets_lock:
        if limit_per_hour not in _budgets:
            _budgets[limit_per_hour] = CallBudget(limit_per_hour)
        return _budgets[limit_per_hour]
