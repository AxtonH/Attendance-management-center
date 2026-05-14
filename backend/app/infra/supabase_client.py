"""Thin Supabase wrapper. Single place that talks to the punch table.

Returns plain Punch objects (domain models). The rest of the codebase never
sees a Supabase response shape, which means we can swap clients or mock for
tests without touching domain or API code.
"""

from datetime import date, datetime, time, timedelta

from supabase import Client, create_client

from app.shared.models import Punch

ATTENDANCE_TABLE = "attendance"
# Supabase / PostgREST defaults to capping responses at 1000 rows. We page
# explicitly to avoid silent truncation on multi-day queries. 1000 matches
# the server cap so each page is a single round-trip filled to capacity.
PAGE_SIZE = 1000
# Max calendar days to look back when searching for the most recent working
# day with punches. 7 days covers weekends and short holiday stretches; if
# nobody has punched in a full week, missing-punch detection isn't the
# pressing problem.
PREVIOUS_WORKING_DAY_LOOKBACK = 7
SELECT_COLS = "transaction_id,emp_code,employee_name,punch_time,punch_state"


class PunchRepository:
    """Read-only access to the Supabase attendance table."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def punches_for_day(self, day: date) -> list[Punch]:
        """All punches with punch_time within the given local day."""
        start = datetime.combine(day, time.min)
        end = start + timedelta(days=1)
        return self._punches_between(start, end)

    def punches_for_previous_working_day(
        self,
        day: date,
        *,
        lookback_days: int = PREVIOUS_WORKING_DAY_LOOKBACK,
    ) -> tuple[date | None, list[Punch]]:
        """Return (working_day, punches) for the most recent day < `day` with punches.

        Strategy: scan the window DESC by punch_time so the very latest rows
        come first. As soon as we cross a calendar-date boundary AND we've
        already collected punches for some date, we stop — every later page
        belongs to older days we don't care about. In the common case (the
        previous working day was yesterday and had ~one day's worth of
        punches), this is a single page round-trip.

        Returns `(None, [])` if the window is empty.
        """
        end = datetime.combine(day, time.min)
        start = end - timedelta(days=lookback_days)

        latest_day: date | None = None
        latest_punches: list[Punch] = []

        for page in self._iter_pages_between(start, end, desc=True):
            for p in page:
                p_day = p.punch_time.date()
                if latest_day is None:
                    latest_day = p_day
                if p_day < latest_day:
                    # We've crossed into older days; we have the full latest day.
                    # Sort ascending for downstream consumers that expect chronological.
                    latest_punches.sort(key=lambda x: x.punch_time)
                    return latest_day, latest_punches
                latest_punches.append(p)

        if latest_day is None:
            return None, []
        latest_punches.sort(key=lambda x: x.punch_time)
        return latest_day, latest_punches

    def _punches_between(self, start: datetime, end: datetime) -> list[Punch]:
        """All punches in [start, end), paginated. Returns chronological order."""
        out: list[Punch] = []
        for page in self._iter_pages_between(start, end, desc=False):
            out.extend(page)
        return out

    def _iter_pages_between(
        self,
        start: datetime,
        end: datetime,
        *,
        desc: bool,
    ):
        """Yield pages of Punches between [start, end), ordered as requested.

        Uses PostgREST `.range(offset, offset+PAGE_SIZE-1)`. Stops when a page
        comes back shorter than PAGE_SIZE — that's the last page. The Supabase
        Python client is synchronous; FastAPI runs sync route handlers in a
        threadpool, so this does not block the event loop.
        """
        offset = 0
        while True:
            response = (
                self._client.table(ATTENDANCE_TABLE)
                .select(SELECT_COLS)
                .gte("punch_time", start.isoformat())
                .lt("punch_time", end.isoformat())
                .order("punch_time", desc=desc)
                .range(offset, offset + PAGE_SIZE - 1)
                .execute()
            )
            rows = response.data or []
            if not rows:
                return
            yield [Punch(**row) for row in rows]
            if len(rows) < PAGE_SIZE:
                return
            offset += PAGE_SIZE


def build_supabase_client(url: str, service_role_key: str) -> Client:
    if not url or not service_role_key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in the environment."
        )
    return create_client(url, service_role_key)
