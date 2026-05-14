import { request } from "@/lib/http";

import { dashboardSchema, type Dashboard } from "./types";

export function getDashboard(date?: string): Promise<Dashboard> {
  return request("/api/dashboard", dashboardSchema, { date });
}
