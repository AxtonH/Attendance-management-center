import { request } from "@/lib/http";

import {
  employeesMonthSchema,
  employeesTodaySchema,
  employeesWeekSchema,
  type EmployeesMonth,
  type EmployeesToday,
  type EmployeesWeek,
} from "./types";

export function getEmployeesToday(date?: string): Promise<EmployeesToday> {
  return request("/api/employees/today", employeesTodaySchema, { date });
}

export function getEmployeesWeek(date?: string): Promise<EmployeesWeek> {
  return request("/api/employees/week", employeesWeekSchema, { date });
}

export function getEmployeesMonth(date?: string): Promise<EmployeesMonth> {
  return request("/api/employees/month", employeesMonthSchema, { date });
}
