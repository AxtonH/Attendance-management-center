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

export type DashboardMode = "daily" | "weekly";

function useDashboardSelector<T>(
  date: string | undefined,
  mode: DashboardMode,
  select: (d: Dashboard) => T,
) {
  return useQuery({
    // mode is part of the key so flipping the tab triggers a fresh fetch
    // and doesn't show stale daily data while weekly is loading.
    queryKey: ["dashboard", date, mode],
    queryFn: () => getDashboard(date, mode),
    refetchInterval: POLL_MS,
    select,
  });
}

export function useDashboard(date?: string, mode: DashboardMode = "daily") {
  return useDashboardSelector(date, mode, (d) => d);
}

export function useOverview(date?: string, mode: DashboardMode = "daily") {
  return useDashboardSelector(date, mode, (d): Overview => d.overview);
}

export function useExceptions(date?: string, mode: DashboardMode = "daily") {
  return useDashboardSelector(date, mode, (d): Exceptions => d.exceptions);
}

export function useArrivals(date?: string, mode: DashboardMode = "daily") {
  return useDashboardSelector(date, mode, (d): Arrivals => d.arrivals);
}

export function useDepartments(date?: string, mode: DashboardMode = "daily") {
  return useDashboardSelector(date, mode, (d): Departments => d.departments);
}
