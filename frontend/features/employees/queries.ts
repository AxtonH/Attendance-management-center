import { useQuery } from "@tanstack/react-query";

import {
  getEmployeesMonth,
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
