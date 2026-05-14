"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

import { todayIso } from "./format";

const ISO_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Read & write the ?date=YYYY-MM-DD URL query param.
 *
 * Defaults to today when the param is missing or malformed. Setting today
 * removes the param entirely so the URL stays clean for the common case.
 */
export function useDateParam(): {
  date: string;            // always a valid YYYY-MM-DD
  isToday: boolean;
  setDate: (next: string | Date) => void;
  clear: () => void;
} {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const today = todayIso();
  const raw = params.get("date");
  const date = raw && ISO_RE.test(raw) ? raw : today;

  const setDate = useCallback(
    (next: string | Date) => {
      const iso = typeof next === "string" ? next : toIso(next);
      const url = iso === today
        ? pathname
        : `${pathname}?date=${iso}`;
      router.push(url, { scroll: false });
    },
    [pathname, router, today],
  );

  const clear = useCallback(() => {
    router.push(pathname, { scroll: false });
  }, [pathname, router]);

  return useMemo(
    () => ({ date, isToday: date === today, setDate, clear }),
    [date, today, setDate, clear],
  );
}

function toIso(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}
