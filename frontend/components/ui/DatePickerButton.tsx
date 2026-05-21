"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { DayPicker } from "react-day-picker";
import "react-day-picker/style.css";

import { parseIsoDate, todayIso } from "@/lib/format";
import { useDateParam } from "@/lib/useDateParam";
import { useRangeParam } from "@/lib/useRangeParam";

// Small inline calendar icon — keeps us free of icon library deps for a
// single use site. ~16px feather-style.
function CalendarIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      className={className}
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Range picker — explicit state machine over react-day-picker's single mode.
//
// We deliberately do NOT use mode="range". Its built-in logic auto-commits
// 1-day ranges on the first click and treats subsequent clicks as
// "modify endpoint" — both behaviors that fought our intended UX in
// earlier attempts. Using mode="single" + custom modifiers gives us:
//
//   - Total control over click semantics (state machine below).
//   - A hover preview that's authored by us, not the library.
//   - No surprise re-renders when the URL params change.
//
// State machine:
//   IDLE       → "no anchor; ready to start a fresh selection"
//   ANCHORED   → "first click made; awaiting second"
//
// Transitions:
//   * Open picker         → IDLE (always, even if a URL range exists)
//   * Click in IDLE       → ANCHORED with that day
//   * Click in ANCHORED   → commit (same-day = daily, different = range), IDLE
//   * Hover in ANCHORED   → updates preview band only
//
// Pre-existing URL range is shown as a *static highlight* on open, but
// doesn't become the working selection — the first click anchors fresh.
// ---------------------------------------------------------------------------

type State =
  | { kind: "idle" }
  | { kind: "anchored"; anchor: Date; hover: Date | null };

export function DatePickerButton() {
  const { date, isToday, clear: clearDate } = useDateParam();
  const { start, end, setRange, clear: clearRange } = useRangeParam();
  // Direct URL writers for the commit path. Bypassing the hook setters
  // (useDateParam.setDate + useRangeParam.clear) when both need to run
  // in the same event loop — otherwise the second hook reads stale
  // searchParams from the first one's closure and resurrects the
  // params we just cleared. One atomic push instead of two.
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [open, setOpen] = useState(false);
  const [state, setState] = useState<State>({ kind: "idle" });
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Dismiss on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("mousedown", onPointerDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onPointerDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const isRange = Boolean(start && end && start !== end);

  // Compute the visible highlighted range. Three sources, in priority order:
  //   1. ANCHORED with a hover  → anchor↔hover (preview band)
  //   2. ANCHORED no hover yet  → anchor only
  //   3. IDLE + URL has a range → start↔end (static; doesn't drive state)
  const highlight: { start: Date; end: Date } | null = useMemo(() => {
    if (state.kind === "anchored") {
      const a = state.anchor;
      const h = state.hover ?? a;
      return h < a ? { start: h, end: a } : { start: a, end: h };
    }
    if (start && end) {
      return { start: parseIsoDate(start), end: parseIsoDate(end) };
    }
    return null;
  }, [state, start, end]);

  // Build the day list for the "in between" modifier. We exclude the
  // endpoints so they can be styled distinctly.
  const inRangeDays = useMemo(() => {
    if (!highlight) return [];
    return daysBetween(highlight.start, highlight.end);
  }, [highlight]);

  function handleDayClick(day: Date) {
    if (state.kind === "idle") {
      setState({ kind: "anchored", anchor: day, hover: null });
      return;
    }
    // ANCHORED — second click commits.
    const a = state.anchor;
    if (isSameDay(a, day)) {
      commitSingle(day);
    } else if (day < a) {
      commitRange(day, a);
    } else {
      commitRange(a, day);
    }
  }

  function handleDayMouseEnter(day: Date) {
    if (state.kind !== "anchored") return;
    // Skip a setState if hover hasn't actually changed — avoids
    // unnecessary re-renders as the cursor crosses adjacent cells.
    if (state.hover && isSameDay(state.hover, day)) return;
    setState({ kind: "anchored", anchor: state.anchor, hover: day });
  }

  function handleDayMouseLeave() {
    if (state.kind !== "anchored") return;
    if (state.hover === null) return;
    setState({ kind: "anchored", anchor: state.anchor, hover: null });
  }

  function commitSingle(day: Date) {
    const iso = toIso(day);
    // Build the new URL in one shot: drop any active range + drop the
    // ?mode=custom flag, and set ?date= (or drop it if the user picked
    // today). Chaining clearRange() + setDate() would race because each
    // hook reads `params` from its own captured closure — the second
    // push would resurrect the params the first one just removed.
    const sp = new URLSearchParams(params.toString());
    sp.delete("start");
    sp.delete("end");
    if (sp.get("mode") === "custom") sp.delete("mode");
    if (iso === todayIso()) {
      sp.delete("date");
    } else {
      sp.set("date", iso);
    }
    const qs = sp.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    closeAndReset();
  }

  function commitRange(s: Date, e: Date) {
    setRange(toIso(s), toIso(e));
    closeAndReset();
  }

  function closeAndReset() {
    setOpen(false);
    setState({ kind: "idle" });
  }

  function handleToggleOpen() {
    setOpen((wasOpen) => {
      const next = !wasOpen;
      // Always open in IDLE — the URL range shows as a static highlight
      // but doesn't become the working selection. Next click starts
      // a brand-new pick (requirement #6).
      if (next) setState({ kind: "idle" });
      return next;
    });
  }

  // While ANCHORED we keep `selected` undefined so react-day-picker
  // doesn't render its own "selected" style on top of our modifiers.
  // The visual is fully driven by inRange/rangeStart/rangeEnd.
  const selected = state.kind === "anchored" ? undefined : undefined;

  return (
    <div ref={wrapperRef} className="relative inline-block">
      <button
        type="button"
        onClick={handleToggleOpen}
        className="inline-flex items-center gap-1 rounded-md border border-border bg-bg-surface px-[8px] py-[6px] text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary"
        title={isRange ? "Pick a date range" : "Pick a date"}
        aria-label="Pick a date or range"
      >
        <CalendarIcon />
        {(!isToday || isRange) && (
          <span className="ml-1 inline-block h-[6px] w-[6px] rounded-full bg-accent" />
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-2 rounded-lg border border-border bg-bg-surface p-2 shadow-lg">
          <DayPicker
            mode="single"
            selected={selected}
            onDayClick={handleDayClick}
            onDayMouseEnter={handleDayMouseEnter}
            onDayMouseLeave={handleDayMouseLeave}
            disabled={{ after: new Date() }}
            weekStartsOn={0}
            showOutsideDays
            defaultMonth={
              start ? parseIsoDate(start) : parseIsoDate(date)
            }
            modifiers={{
              inRange: inRangeDays,
              rangeStart: highlight ? [highlight.start] : [],
              rangeEnd: highlight ? [highlight.end] : [],
            }}
            modifiersClassNames={{
              inRange: "rdp-in-range",
              rangeStart: "rdp-range-start",
              rangeEnd: "rdp-range-end",
            }}
          />
          <div className="flex items-center justify-between border-t border-border px-2 py-2">
            <button
              type="button"
              onClick={() => {
                clearRange();
                clearDate();
                closeAndReset();
              }}
              className="text-[12px] text-text-secondary hover:text-text-primary"
            >
              Today
            </button>
            <span className="text-[11px] text-text-tertiary">
              {isRange
                ? `${start} → ${end}`
                : isToday
                  ? "Showing today"
                  : `Showing ${date}`}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

function toIso(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function isSameDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

// Inclusive-exclusive list: the days strictly between start and end.
// Endpoints are excluded so they can be styled distinctly via their
// own modifiers. Returns [] when the range is a single day.
function daysBetween(start: Date, end: Date): Date[] {
  if (isSameDay(start, end)) return [];
  const out: Date[] = [];
  const cursor = new Date(start);
  cursor.setDate(cursor.getDate() + 1);
  while (cursor < end) {
    out.push(new Date(cursor));
    cursor.setDate(cursor.getDate() + 1);
  }
  return out;
}

// Re-export so consumers don't need a second import.
export { useDateParam };
export const today = todayIso;
