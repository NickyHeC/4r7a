"""In-memory rate limiting for bridge MCP (v1)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    reads_per_minute: int = 60
    report_blocker_per_day: int = 20
    _read_times: dict[str, deque[float]] = field(default_factory=lambda: defaultdict(deque))
    _report_day: dict[str, tuple[str, int]] = field(default_factory=dict)

    def check_read(self, member: str) -> bool:
        return self._count_in_window(member, self._read_times, 60) < self.reads_per_minute

    def record_read(self, member: str) -> None:
        self._append_window(member, self._read_times, 60)

    def check_report(self, member: str) -> bool:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        key = member
        stored = self._report_day.get(key)
        if stored is None or stored[0] != day:
            return True
        return stored[1] < self.report_blocker_per_day

    def record_report(self, member: str) -> None:
        day = time.strftime("%Y-%m-%d", time.gmtime())
        key = member
        stored = self._report_day.get(key)
        if stored is None or stored[0] != day:
            self._report_day[key] = (day, 1)
        else:
            self._report_day[key] = (day, stored[1] + 1)

    def _count_in_window(self, member: str, store: dict[str, deque[float]], seconds: int) -> int:
        now = time.time()
        q = store[member]
        while q and now - q[0] > seconds:
            q.popleft()
        return len(q)

    def _append_window(self, member: str, store: dict[str, deque[float]], seconds: int) -> None:
        now = time.time()
        q = store[member]
        while q and now - q[0] > seconds:
            q.popleft()
        q.append(now)
