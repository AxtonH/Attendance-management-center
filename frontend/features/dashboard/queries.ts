import { useQuery } from "@tanstack/react-query";

import { getDashboard } from "./api";
import type {
  Arrivals,
  Dashboard,
  Departments,
  Exceptions,
  Overview,
} from "./types";

// One query backs every panel. Components subscribe to a slice via `select`,
// which means React only re-renders the components whose slice changed.
//
// 60s polling matches the "live feel" requirement while staying well inside
// what BioTime can push (every 5 min).
const POLL_MS = 60_000;

export type DashboardMode = "daily" | "weekly" | "monthly" | "custom";
export type DashboardRange = { start?: string | null; end?: string | null };

function useDashboardSelector<T>(
  date: string | undefined,
  mode: DashboardMode,
  range: DashboardRange | undefined,
  select: (d: Dashboard) => T,
) {
  // Range is part of the cache key so a fresh ?start/?end triggers a new
  // fetch in custom mode. For non-custom modes the values are null and
  // contribute nothing to the key.
  const rangeKey =
    mode === "custom" ? `${range?.start ?? ""}_${range?.end ?? ""}` : "";
  return useQuery({
    queryKey: ["dashboard", date, mode, rangeKey],
    queryFn: () => getDashboard(date, mode, range),
    refetchInterval: POLL_MS,
    select,
  });
}

export function useDashboard(
  date?: string,
  mode: DashboardMode = "daily",
  range?: DashboardRange,
) {
  return useDashboardSelector(date, mode, range, (d) => d);
}

export function useOverview(
  date?: string,
  mode: DashboardMode = "daily",
  range?: DashboardRange,
) {
  return useDashboardSelector(date, mode, range, (d): Overview => d.overview);
}

export function useExceptions(
  date?: string,
  mode: DashboardMode = "daily",
  range?: DashboardRange,
) {
  return useDashboardSelector(
    date,
    mode,
    range,
    (d): Exceptions => d.exceptions,
  );
}

export function useArrivals(
  date?: string,
  mode: DashboardMode = "daily",
  range?: DashboardRange,
) {
  return useDashboardSelector(date, mode, range, (d): Arrivals => d.arrivals);
}

export function useDepartments(
  date?: string,
  mode: DashboardMode = "daily",
  range?: DashboardRange,
) {
  return useDashboardSelector(
    date,
    mode,
    range,
    (d): Departments => d.departments,
  );
}
