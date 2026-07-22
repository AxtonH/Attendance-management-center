import { API_BASE } from "@/lib/http";
import type { DashboardMode } from "@/lib/useModeParam";

export type ExportFormat = "excel" | "pdf";

/** The view state a report is scoped to — same params the pages read. */
export type ReportView = {
  mode: DashboardMode;
  date: string; // YYYY-MM-DD (daily/weekly/monthly anchor)
  start: string | null; // custom range edges
  end: string | null;
};

/**
 * Build the export download URL for the current view + selection.
 *
 * `empCodes` is the dialog's selection; pass null for "everyone" so the
 * URL stays clean (and the backend defaults to the full roster) when no
 * one was deselected.
 */
export function buildExportUrl(
  format: ExportFormat,
  view: ReportView,
  empCodes: string[] | null,
): string {
  const url = new URL(`${API_BASE}/api/exports/employees`);
  url.searchParams.set("format", format);
  if (view.mode !== "daily") url.searchParams.set("mode", view.mode);
  if (view.mode === "custom") {
    if (view.start) url.searchParams.set("start", view.start);
    if (view.end) url.searchParams.set("end", view.end);
  } else {
    // date drives daily/weekly/monthly; omit when it's today (backend
    // defaults to today), matching the clean-URL convention elsewhere.
    if (view.date) url.searchParams.set("date", view.date);
  }
  if (empCodes !== null) url.searchParams.set("emp_codes", empCodes.join(","));
  return url.toString();
}

/**
 * Fetch the export as a blob and save it, honoring the server filename.
 * Fetched as a blob so the cross-origin Content-Disposition is respected.
 * Throws on a non-OK response — callers surface the error state.
 */
export async function downloadExport(
  format: ExportFormat,
  view: ReportView,
  empCodes: string[] | null,
): Promise<void> {
  const res = await fetch(buildExportUrl(format, view, empCodes), {
    headers: { Accept: "*/*" },
  });
  if (!res.ok) throw new Error(`Export failed: ${res.status}`);
  const blob = await res.blob();
  const filename = filenameFromDisposition(
    res.headers.get("Content-Disposition"),
    format,
  );
  triggerDownload(blob, filename);
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
