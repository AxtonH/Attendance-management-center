import { request } from "@/lib/http";

import { employeesTodaySchema, type EmployeesToday } from "./types";

export function getEmployeesToday(date?: string): Promise<EmployeesToday> {
  return request("/api/employees/today", employeesTodaySchema, { date });
}
