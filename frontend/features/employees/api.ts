import { request } from "@/lib/http";

import {
  employeesTodaySchema,
  employeesWeekSchema,
  type EmployeesToday,
  type EmployeesWeek,
} from "./types";

export function getEmployeesToday(date?: string): Promise<EmployeesToday> {
  return request("/api/employees/today", employeesTodaySchema, { date });
}

export function getEmployeesWeek(date?: string): Promise<EmployeesWeek> {
  return request("/api/employees/week", employeesWeekSchema, { date });
}
