"use client";

import { useEffect, useRef, useState } from "react";
import { DayPicker } from "react-day-picker";
import "react-day-picker/style.css";

import { parseIsoDate, todayIso } from "@/lib/format";
import { useDateParam } from "@/lib/useDateParam";

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

export function DatePickerButton() {
  const { date, isToday, setDate, clear } = useDateParam();
  const [open, setOpen] = useState(false);
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

  const selected = parseIsoDate(date);

  return (
    <div ref={wrapperRef} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-1 rounded-md border border-border bg-bg-surface px-[8px] py-[6px] text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary"
        title="Pick a date"
        aria-label="Pick a date"
      >
        <CalendarIcon />
        {!isToday && (
          <span className="ml-1 inline-block h-[6px] w-[6px] rounded-full bg-accent" />
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-2 rounded-lg border border-border bg-bg-surface p-2 shadow-lg">
          <DayPicker
            mode="single"
            selected={selected}
            onSelect={(d) => {
              if (!d) return;
              setDate(d);
              setOpen(false);
            }}
            // Don't let users pick the future — there's no data yet.
            disabled={{ after: new Date() }}
            weekStartsOn={0}
            showOutsideDays
          />
          <div className="flex items-center justify-between border-t border-border px-2 py-2">
            <button
              type="button"
              onClick={() => {
                clear();
                setOpen(false);
              }}
              className="text-[12px] text-text-secondary hover:text-text-primary"
            >
              Today
            </button>
            <span className="text-[11px] text-text-tertiary">
              {isToday ? "Showing today" : `Showing ${date}`}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

// Re-export so consumers don't need a second import.
export { useDateParam };
export const today = todayIso;
