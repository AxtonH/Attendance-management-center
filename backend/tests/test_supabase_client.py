"""Tests for PunchRepository's pagination + previous-working-day logic.

A small fake stands in for the Supabase query builder. It respects:
  - .gte / .lt filters on punch_time
  - .order(desc=True/False)
  - .range(start, end) — the pagination mechanism we depend on

The bug we're guarding against: PostgREST silently caps responses at 1000
rows. Multi-day queries that exceed that cap used to drop the rows past
the limit, which (with ascending order) meant the latest punches went
missing — exactly the "punched 16:39 but flagged missing punch" symptom.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from app.infra.supabase_client import PAGE_SIZE, PunchRepository


@dataclass
class _Response:
    data: list[dict[str, Any]]


@dataclass
class _Query:
    """Tiny chainable fake of supabase-py's query builder."""

    rows: list[dict[str, Any]]
    _start: datetime | None = None
    _end: datetime | None = None
    _desc: bool = False
    _range: tuple[int, int] | None = None
    calls: list[tuple[int, int]] = field(default_factory=list)

    def select(self, _cols: str) -> "_Query":
        return self

    def gte(self, _col: str, value: str) -> "_Query":
        self._start = datetime.fromisoformat(value)
        return self

    def lt(self, _col: str, value: str) -> "_Query":
        self._end = datetime.fromisoformat(value)
        return self

    def order(self, _col: str, desc: bool) -> "_Query":
        self._desc = desc
        return self

    def range(self, start: int, end: int) -> "_Query":
        self._range = (start, end)
        return self

    def execute(self) -> _Response:
        assert self._start is not None and self._end is not None
        filtered = [
            r for r in self.rows
            if self._start <= datetime.fromisoformat(r["punch_time"]) < self._end
        ]
        filtered.sort(
            key=lambda r: datetime.fromisoformat(r["punch_time"]),
            reverse=self._desc,
        )
        if self._range is not None:
            lo, hi = self._range
            self.calls.append((lo, hi))
            filtered = filtered[lo : hi + 1]
        return _Response(data=filtered)


@dataclass
class _FakeClient:
    rows: list[dict[str, Any]]
    last_query: _Query | None = None

    def table(self, _name: str) -> _Query:
        # Each new table() call starts a fresh query, mirroring supabase-py.
        self.last_query = _Query(rows=self.rows)
        return self.last_query


def _row(emp_code: str, dt: datetime, tid: int) -> dict[str, Any]:
    return {
        "transaction_id": tid,
        "emp_code": emp_code,
        "employee_name": None,
        "punch_time": dt.isoformat(),
        "punch_state": "0",
    }


class TestPagination:
    def test_handles_multi_page_response(self):
        # Build PAGE_SIZE + 50 rows across a single day so a non-paginated
        # query would lose the last 50.
        day = date(2026, 5, 13)
        rows = [
            _row(f"E{i:04d}", datetime.combine(day, datetime.min.time())
                 + timedelta(minutes=i), tid=i)
            for i in range(PAGE_SIZE + 50)
        ]
        repo = PunchRepository(_FakeClient(rows))  # type: ignore[arg-type]
        result = repo.punches_for_day(day)
        assert len(result) == PAGE_SIZE + 50

    def test_single_page_when_under_limit(self):
        day = date(2026, 5, 13)
        rows = [
            _row("1001", datetime.combine(day, datetime.min.time())
                 + timedelta(hours=h), tid=h)
            for h in range(10)
        ]
        client = _FakeClient(rows)
        repo = PunchRepository(client)  # type: ignore[arg-type]
        result = repo.punches_for_day(day)
        assert len(result) == 10
        # Verify exactly one page was requested (single round-trip).
        assert client.last_query is not None
        assert len(client.last_query.calls) == 1


class TestPreviousWorkingDay:
    def test_finds_latest_day_with_punches(self):
        # Punches across 13th and 12th. From 14th's perspective, 13th wins.
        rows = [
            _row("1001", datetime(2026, 5, 12, 9, 0), tid=1),
            _row("1001", datetime(2026, 5, 13, 8, 45), tid=2),
            _row("1001", datetime(2026, 5, 13, 16, 39), tid=3),
        ]
        repo = PunchRepository(_FakeClient(rows))  # type: ignore[arg-type]
        prev_day, prev_punches = repo.punches_for_previous_working_day(
            date(2026, 5, 14)
        )
        assert prev_day == date(2026, 5, 13)
        # The bug scenario: both 08:45 and 16:39 must be present.
        assert len(prev_punches) == 2
        assert prev_punches[0].punch_time < prev_punches[1].punch_time

    def test_regression_latest_punch_not_truncated(self):
        # Reproduce the screenshot: enough rows in the lookback window to
        # exceed one page. The very latest punch (16:39 on the 13th) must
        # still be present after pagination.
        rows: list[dict[str, Any]] = []
        # Filler: lots of older punches in the lookback window.
        base = datetime(2026, 5, 1, 9, 0)
        for i in range(PAGE_SIZE):
            rows.append(_row(f"E{i:04d}", base + timedelta(minutes=i), tid=i))
        # The two punches we care about — newest of all.
        rows.append(_row("OMAR", datetime(2026, 5, 13, 8, 45), tid=9001))
        rows.append(_row("OMAR", datetime(2026, 5, 13, 16, 39), tid=9002))

        repo = PunchRepository(_FakeClient(rows))  # type: ignore[arg-type]
        prev_day, prev_punches = repo.punches_for_previous_working_day(
            date(2026, 5, 14)
        )
        assert prev_day == date(2026, 5, 13)
        omar = [p for p in prev_punches if p.emp_code == "OMAR"]
        assert len(omar) == 2  # Both punches present → not flagged as missing.

    def test_empty_window_returns_none(self):
        repo = PunchRepository(_FakeClient([]))  # type: ignore[arg-type]
        prev_day, prev_punches = repo.punches_for_previous_working_day(
            date(2026, 5, 14)
        )
        assert prev_day is None
        assert prev_punches == []

    def test_desc_scan_stops_early_on_day_boundary(self):
        # If the latest day fits in a single page, we should only need
        # one round-trip even when older days have lots of data.
        rows: list[dict[str, Any]] = []
        # 2026-05-13: only 5 punches.
        for i in range(5):
            rows.append(
                _row("OMAR", datetime(2026, 5, 13, 8, i), tid=1000 + i)
            )
        # 2026-05-12 and earlier: tons of punches.
        base = datetime(2026, 5, 1, 9, 0)
        for i in range(PAGE_SIZE):
            rows.append(_row(f"E{i:04d}", base + timedelta(minutes=i), tid=i))

        client = _FakeClient(rows)
        repo = PunchRepository(client)  # type: ignore[arg-type]
        prev_day, prev_punches = repo.punches_for_previous_working_day(
            date(2026, 5, 14)
        )
        assert prev_day == date(2026, 5, 13)
        assert len(prev_punches) == 5
        # Only the first page was needed because the boundary was visible
        # within the first PAGE_SIZE rows of the DESC scan.
        assert client.last_query is not None
        assert len(client.last_query.calls) == 1
