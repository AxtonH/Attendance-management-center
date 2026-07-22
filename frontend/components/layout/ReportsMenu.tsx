"use client";

import { useState } from "react";

import { ReportDialog } from "@/features/reports/components/ReportDialog";
import type { ReportView } from "@/features/reports/download";
import { useDateParam } from "@/lib/useDateParam";
import { useModeParam } from "@/lib/useModeParam";
import { useRangeParam } from "@/lib/useRangeParam";

/**
 * "Reports" entry in the TopBar. Opens the report dialog: pick who to
 * include (filter by department, toggle per person), then download the
 * period being viewed as Excel or PDF.
 *
 * Works from any page: the TopBar carries the view params across tabs, so
 * whether the user is on Dashboard or Employees the report always reflects
 * the active period (?date / ?mode / ?start / ?end).
 */
export function ReportsMenu() {
  const { date } = useDateParam();
  const { mode } = useModeParam();
  const { start, end } = useRangeParam();
  const [open, setOpen] = useState(false);

  // Same "valid custom only when both edges present and distinct" rule the
  // pages apply, so a stale ?mode=custom without a real range exports daily.
  const effectiveMode =
    mode === "custom" && start && end && start !== end ? "custom" : mode;
  const view: ReportView = { mode: effectiveMode, date, start, end };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="cursor-pointer text-text-on-dark-muted hover:text-text-on-dark"
      >
        Reports
      </button>
      {open && <ReportDialog view={view} onClose={() => setOpen(false)} />}
    </>
  );
}
