import { z } from "zod";

// Mirrors backend/app/features/employees/models.py.

export const employeeDaySchema = z.object({
  emp_code: z.string(),
  name: z.string(),
  punch_in: z.string().nullable(),  // ISO datetime string; null when absent / on leave / holiday
  punch_out: z.string().nullable(),
  worked_minutes: z.number().int().nonnegative().nullable(),
  absent: z.boolean(),
  on_leave: z.boolean(),
  on_holiday: z.boolean(),
});
export type EmployeeDay = z.infer<typeof employeeDaySchema>;

export const employeesTodaySchema = z.object({
  date: z.string(),
  rows: z.array(employeeDaySchema),
});
export type EmployeesToday = z.infer<typeof employeesTodaySchema>;

// Weekly view: one parent row per employee with N child rows for the
// days they punched. Mirrors backend EmployeesWeekResponse.
export const employeeWeekDaySchema = z.object({
  date: z.string(),  // ISO YYYY-MM-DD
  punch_in: z.string().nullable(),  // null when absent / on leave / holiday
  punch_out: z.string().nullable(),
  worked_minutes: z.number().int().nonnegative().nullable(),
  absent: z.boolean(),
  on_leave: z.boolean(),
  on_holiday: z.boolean(),
});
export type EmployeeWeekDay = z.infer<typeof employeeWeekDaySchema>;

export const employeeWeekSchema = z.object({
  emp_code: z.string(),
  name: z.string(),
  days_worked: z.number().int().nonnegative(),
  expected_days: z.number().int().nonnegative(),
  total_worked_minutes: z.number().int().nonnegative(),
  expected_minutes: z.number().int().nonnegative(),
  days: z.array(employeeWeekDaySchema),
});
export type EmployeeWeek = z.infer<typeof employeeWeekSchema>;

export const employeesWeekSchema = z.object({
  range_start: z.string(),
  range_end: z.string(),
  rows: z.array(employeeWeekSchema),
});
export type EmployeesWeek = z.infer<typeof employeesWeekSchema>;

// Monthly view: same per-row shape as weekly (employee + their daily
// children). `expected_*` fields on each row are present but unused —
// month length and holidays make a fixed expected-hours target
// meaningless at this scale.
export const employeesMonthSchema = z.object({
  range_start: z.string(),
  range_end: z.string(),
  rows: z.array(employeeWeekSchema),
});
export type EmployeesMonth = z.infer<typeof employeesMonthSchema>;
