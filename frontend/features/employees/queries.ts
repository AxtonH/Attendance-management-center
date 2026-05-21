import { useQuery } from "@tanstack/react-query";

import {
  getEmployeesMonth,
  getEmployeesRange,
  getEmployeesToday,
  getEmployeesWeek,
} from "./api";

const POLL_MS = 60_000;

export function useEmployeesToday(date?: string) {
  return useQuery({
    queryKey: ["employees-today", date],
    queryFn: () => getEmployeesToday(date),
    refetchInterval: POLL_MS,
  });
}

export function useEmployeesWeek(date?: string) {
  return useQuery({
    queryKey: ["employees-week", date],
    queryFn: () => getEmployeesWeek(date),
    refetchInterval: POLL_MS,
  });
}

export function useEmployeesMonth(date?: string) {
  return useQuery({
    queryKey: ["employees-month", date],
    queryFn: () => getEmployeesMonth(date),
    refetchInterval: POLL_MS,
  });
}

export function useEmployeesRange(start: string | null, end: string | null) {
  return useQuery({
    queryKey: ["employees-range", start, end],
    queryFn: () => getEmployeesRange(start!, end!),
    // Don't fire until both edges are populated — guards against a
    // brief render with start but no end (or vice versa) during a
    // URL-driven re-render.
    enabled: Boolean(start && end),
    refetchInterval: POLL_MS,
  });
}
