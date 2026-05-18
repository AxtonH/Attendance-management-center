import { z } from "zod";

// Mirrors the Pydantic models in backend/app/features/dashboard/models.py.
// Keep them in lockstep — if you change one, change the other.

export const overviewSchema = z.object({
  date: z.string(),
  present: z.number().int().nonnegative(),
  late: z.number().int().nonnegative(),
  // Phase 1: backend returns null because there's no roster to compare against.
  absent: z.number().int().nonnegative().nullable(),
});
export type Overview = z.infer<typeof overviewSchema>;

export const exceptionSeverity = z.enum(["high", "medium", "low"]);
export const exceptionTag = z.enum([
  "absent",
  "late",
  "missing_punch",
  "incomplete_hours",
  "pattern",
  "review",
]);

export const exceptionItemSchema = z.object({
  emp_code: z.string(),
  name: z.string(),
  department: z.string(),
  severity: exceptionSeverity,
  tag: exceptionTag,
  detail: z.string(),
  // Weekly view only: short weekday labels ("Mon", "Wed") on which this
  // exception fired. Absent/null in daily view = single-day flag.
  days: z.array(z.string()).nullable().optional(),
});
export type ExceptionItem = z.infer<typeof exceptionItemSchema>;

export const exceptionsSchema = z.object({
  date: z.string(),
  total: z.number().int().nonnegative(),
  items: z.array(exceptionItemSchema),
});
export type Exceptions = z.infer<typeof exceptionsSchema>;

export const departmentRollupSchema = z.object({
  name: z.string(),
  expected: z.number().int().nonnegative(),
  present: z.number().int().nonnegative(),
  late: z.number().int().nonnegative(),
  absent: z.number().int().nonnegative(),
});
export type DepartmentRollup = z.infer<typeof departmentRollupSchema>;

export const departmentsSchema = z.object({
  date: z.string(),
  departments: z.array(departmentRollupSchema),
});
export type Departments = z.infer<typeof departmentsSchema>;

export const arrivalBucketSchema = z.object({
  label: z.string(),
  count: z.number().int().nonnegative(),
});
export type ArrivalBucket = z.infer<typeof arrivalBucketSchema>;

export const arrivalsSchema = z.object({
  date: z.string(),
  bucket_minutes: z.number().int().positive(),
  buckets: z.array(arrivalBucketSchema),
});
export type Arrivals = z.infer<typeof arrivalsSchema>;

export const dashboardSchema = z.object({
  date: z.string(),
  // Required — backend always sends it. Keeping it required gives a clean
  // Dashboard type with `mode: "daily" | "weekly" | "monthly"` and avoids
  // the unknown-leak from .default/.catch under zod 3.23's input inference.
  mode: z.enum(["daily", "weekly", "monthly"]),
  range_start: z.string().nullable().optional(),
  range_end: z.string().nullable().optional(),
  overview: overviewSchema,
  exceptions: exceptionsSchema,
  arrivals: arrivalsSchema,
  departments: departmentsSchema,
});
export type Dashboard = z.infer<typeof dashboardSchema>;

export type FilterType =
  | "all"
  | "late"
  | "absent"
  | "missing_punch"
  | "incomplete_hours"
  | "review";
