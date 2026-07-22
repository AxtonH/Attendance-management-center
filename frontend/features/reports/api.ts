import { request } from "@/lib/http";

import { exportRosterSchema, type ExportRoster } from "./types";
import type { ReportView } from "./download";

/**
 * Employees selectable in the report dialog (code, name, department).
 * The view params matter only for the backend's phase-1 fallback (roster
 * derived from the period's punches); with Odoo wired they're ignored.
 */
export function getExportRoster(view: ReportView): Promise<ExportRoster> {
  return request("/api/exports/roster", exportRosterSchema, {
    mode: view.mode !== "daily" ? view.mode : undefined,
    date: view.mode !== "custom" ? view.date : undefined,
    start: view.mode === "custom" ? view.start ?? undefined : undefined,
    end: view.mode === "custom" ? view.end ?? undefined : undefined,
  });
}
