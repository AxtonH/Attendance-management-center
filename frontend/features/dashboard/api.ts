import { request } from "@/lib/http";

import { dashboardSchema, type Dashboard } from "./types";

export function getDashboard(
  date?: string,
  mode: "daily" | "weekly" | "monthly" | "custom" = "daily",
  range?: { start?: string | null; end?: string | null },
): Promise<Dashboard> {
  return request("/api/dashboard", dashboardSchema, {
    date,
    // Skip the param entirely when daily — keeps URLs clean and the
    // backend default kicks in.
    mode: mode === "daily" ? undefined : mode,
    // Range params only flow when mode is custom; the backend ignores
    // them otherwise but no point sending noise.
    start: mode === "custom" ? range?.start ?? undefined : undefined,
    end: mode === "custom" ? range?.end ?? undefined : undefined,
  });
}
