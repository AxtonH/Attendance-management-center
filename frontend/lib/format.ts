// Date formatters — kept in one place so the org's DD/MM/YYYY convention
// is applied consistently.

const FULL_DATE = new Intl.DateTimeFormat("en-GB", {
  weekday: "long",
  day: "numeric",
  month: "long",
  year: "numeric",
});

export function formatFullDate(date: Date = new Date()): string {
  return FULL_DATE.format(date);
}

/** Parse "YYYY-MM-DD" into a local Date (midnight, no tz drift). */
export function parseIsoDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function formatIsoFullDate(iso: string): string {
  return formatFullDate(parseIsoDate(iso));
}

/**
 * Compute the Sunday-anchored week range for an ISO date.
 * Mirrors `week_range_for` on the backend so the header label is
 * available immediately without waiting on the API response.
 */
export function weekRangeFor(iso: string): { start: Date; end: Date } {
  const anchor = parseIsoDate(iso);
  // Python's weekday() puts Sun=6; we need offset 0 for Sun → use (day+1)%7
  // where `day` is JS's getDay() (Sun=0..Sat=6). That formula already gives
  // 0 for Sunday in JS, so we can use getDay() directly.
  const daysSinceSunday = anchor.getDay(); // Sun=0..Sat=6
  const start = new Date(anchor);
  start.setDate(anchor.getDate() - daysSinceSunday);
  const end = new Date(start);
  end.setDate(start.getDate() + 6);
  return { start, end };
}

/**
 * Render the calendar month containing the ISO date as "May 2026".
 * Mirrors the backend's `month_range_for` for the header label.
 */
export function formatMonthLabel(iso: string): string {
  const d = parseIsoDate(iso);
  return new Intl.DateTimeFormat("en-GB", {
    month: "long",
    year: "numeric",
  }).format(d);
}

/**
 * Render a Sun–Sat week as "10 May – 16 May 2026". When the range spans
 * two months it expands to "28 Apr – 4 May 2026"; spanning two years
 * shows both years.
 */
export function formatWeekRange(iso: string): string {
  const { start, end } = weekRangeFor(iso);
  const dayMonth = new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
  });
  const dayMonthYear = new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
  const sameMonth =
    start.getMonth() === end.getMonth() && start.getFullYear() === end.getFullYear();
  const sameYear = start.getFullYear() === end.getFullYear();
  if (sameMonth) {
    return `${start.getDate()} – ${end.getDate()} ${dayMonthYear
      .format(end)
      .split(" ")
      .slice(1)
      .join(" ")}`;
  }
  if (sameYear) {
    return `${dayMonth.format(start)} – ${dayMonthYear.format(end)}`;
  }
  return `${dayMonthYear.format(start)} – ${dayMonthYear.format(end)}`;
}

/** "09:05" from an ISO datetime string. Returns "—" if input is null/invalid. */
export function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/** "7h 54m" from a minutes count. "—" when null/undefined. */
export function formatWorkedMinutes(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return "—";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}h ${m.toString().padStart(2, "0")}m`;
}

export function todayIso(): string {
  const d = new Date();
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}
