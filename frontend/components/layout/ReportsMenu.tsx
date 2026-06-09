"use client";

import { useEffect, useRef, useState } from "react";

import { API_BASE } from "@/lib/http";
import { useDateParam } from "@/lib/useDateParam";
import { useModeParam } from "@/lib/useModeParam";
import { useRangeParam } from "@/lib/useRangeParam";

type ExportFormat = "excel" | "pdf";

/**
 * "Reports" dropdown in the TopBar. Two actions — Excel and PDF — each
 * downloads the Employees attendance data for the period currently being
 * viewed (the same ?date / ?mode / ?start / ?end the pages read).
 *
 * Works from any page: the TopBar carries the view params across tabs, so
 * whether the user is on Dashboard or Employees the export always reflects
 * the active period. The file is fetched as a blob so the cross-origin
 * server filename (Content-Disposition) is honored on download.
 */
export function ReportsMenu() {
  const { date } = useDateParam();
  const { mode } = useModeParam();
  const { start, end } = useRangeParam();

  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [error, setError] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  // Edge's axe lint can't statically resolve a JSX expression on
  // aria-expanded and flags a false positive; passing it via spread
  // satisfies the rule while React still serializes the boolean. Same
  // workaround used in ExceptionsPanel / EmployeesWeekTable.
  const ariaProps: { "aria-expanded": boolean } = { "aria-expanded": open };

  // Same "valid custom only when both edges present and distinct" rule the
  // pages apply, so a stale ?mode=custom without a real range exports daily.
  const effectiveMode =
    mode === "custom" && start && end && start !== end ? "custom" : mode;

  // Close on outside click / Escape — standard menu affordance.
  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (!containerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const buildUrl = (format: ExportFormat): string => {
    const url = new URL(`${API_BASE}/api/exports/employees`);
    url.searchParams.set("format", format);
    if (effectiveMode !== "daily") url.searchParams.set("mode", effectiveMode);
    if (effectiveMode === "custom") {
      if (start) url.searchParams.set("start", start);
      if (end) url.searchParams.set("end", end);
    } else {
      // date drives daily/weekly/monthly; omit when it's today (backend
      // defaults to today), matching the clean-URL convention elsewhere.
      if (date) url.searchParams.set("date", date);
    }
    return url.toString();
  };

  const download = async (format: ExportFormat) => {
    setBusy(format);
    setError(false);
    try {
      const res = await fetch(buildUrl(format), {
        headers: { Accept: "*/*" },
      });
      if (!res.ok) throw new Error(`Export failed: ${res.status}`);
      const blob = await res.blob();
      const filename = filenameFromDisposition(
        res.headers.get("Content-Disposition"),
        format,
      );
      triggerDownload(blob, filename);
      setOpen(false);
    } catch {
      setError(true);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="true"
        {...ariaProps}
        className="flex cursor-pointer items-center gap-1 text-text-on-dark-muted hover:text-text-on-dark"
      >
        <span className={open ? "text-text-on-dark" : ""}>Reports</span>
        <Chevron open={open} />
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-[180px] overflow-hidden rounded-lg border border-black/10 bg-white py-1 text-text-primary shadow-lg">
          <MenuItem
            label="Export to Excel"
            hint=".xlsx"
            busy={busy === "excel"}
            onClick={() => download("excel")}
          />
          <MenuItem
            label="Export to PDF"
            hint=".pdf"
            busy={busy === "pdf"}
            onClick={() => download("pdf")}
          />
          {error && (
            <p className="px-3 py-2 text-[11px] text-danger-text">
              Export failed. Try again.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function MenuItem({
  label,
  hint,
  busy,
  onClick,
}: {
  label: string;
  hint: string;
  busy: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy}
      className="flex w-full items-center justify-between px-3 py-[8px] text-left text-[13px] hover:bg-bg-subtle disabled:opacity-50"
    >
      <span>{busy ? "Preparing…" : label}</span>
      {!busy && <span className="text-[11px] text-text-tertiary">{hint}</span>}
    </button>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="10"
      height="10"
      viewBox="0 0 12 12"
      fill="none"
      className={`transition-transform ${open ? "rotate-180" : ""}`}
      aria-hidden
    >
      <path
        d="M2.5 4.5L6 8L9.5 4.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** Pull the filename out of a Content-Disposition header, with a fallback. */
function filenameFromDisposition(
  header: string | null,
  format: ExportFormat,
): string {
  const fallback = `prezlab-attendance.${format === "pdf" ? "pdf" : "xlsx"}`;
  if (!header) return fallback;
  const match = /filename="?([^"]+)"?/.exec(header);
  return match?.[1] ?? fallback;
}

/** Save a blob to disk by clicking a transient object-URL anchor. */
function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke on the next tick so the click has committed the navigation.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
