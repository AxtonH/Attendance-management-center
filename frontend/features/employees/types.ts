import { z } from "zod";

// Mirrors backend/app/features/employees/models.py.

export const employeeDaySchema = z.object({
  emp_code: z.string(),
  name: z.string(),
  punch_in: z.string(),  // ISO datetime string
  punch_out: z.string().nullable(),
  worked_minutes: z.number().int().nonnegative().nullable(),
});
export type EmployeeDay = z.infer<typeof employeeDaySchema>;

export const employeesTodaySchema = z.object({
  date: z.string(),
  rows: z.array(employeeDaySchema),
});
export type EmployeesToday = z.infer<typeof employeesTodaySchema>;
