import { useQuery } from "@tanstack/react-query";

import { getEmployeesToday } from "./api";

const POLL_MS = 60_000;

export function useEmployeesToday(date?: string) {
  return useQuery({
    queryKey: ["employees-today", date],
    queryFn: () => getEmployeesToday(date),
    refetchInterval: POLL_MS,
  });
}
