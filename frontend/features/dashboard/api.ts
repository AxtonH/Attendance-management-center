import { request } from "@/lib/http";

import { dashboardSchema, type Dashboard } from "./types";

export function getDashboard(
  date?: string,
  mode: "daily" | "weekly" = "daily",
): Promise<Dashboard> {
  return request("/api/dashboard", dashboardSchema, {
    date,
    // Skip the param entirely when daily — keeps URLs clean and the
    // backend default kicks in.
    mode: mode === "daily" ? undefined : mode,
  });
}
