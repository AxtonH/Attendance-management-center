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

function useDashboardSelector<T>(
  date: string | undefined,
  select: (d: Dashboard) => T,
) {
  return useQuery({
    queryKey: ["dashboard", date],
    queryFn: () => getDashboard(date),
    refetchInterval: POLL_MS,
    select,
  });
}

export function useDashboard(date?: string) {
  return useDashboardSelector(date, (d) => d);
}

export function useOverview(date?: string) {
  return useDashboardSelector(date, (d): Overview => d.overview);
}

export function useExceptions(date?: string) {
  return useDashboardSelector(date, (d): Exceptions => d.exceptions);
}

export function useArrivals(date?: string) {
  return useDashboardSelector(date, (d): Arrivals => d.arrivals);
}

export function useDepartments(date?: string) {
  return useDashboardSelector(date, (d): Departments => d.departments);
}
