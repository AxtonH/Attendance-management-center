"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

const ISO_RE = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Read & write the ?start=YYYY-MM-DD&end=YYYY-MM-DD URL query params.
 *
 * The picker uses these to drive custom-range mode on the dashboard.
 * When both are present and valid, `range` is populated. Setting a
 * range writes both params (or clears them when the range is the same
 * start/end, which the backend treats as a single-day view).
 *
 * Preserves every other search param on change so flipping the picker
 * doesn't drop ?mode= or any future siblings.
 */
export function useRangeParam(): {
  start: string | null;
  end: string | null;
  setRange: (start: string, end: string) => void;
  clear: () => void;
} {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const rawStart = params.get("start");
  const rawEnd = params.get("end");
  const start = rawStart && ISO_RE.test(rawStart) ? rawStart : null;
  const end = rawEnd && ISO_RE.test(rawEnd) ? rawEnd : null;

  const setRange = useCallback(
    (s: string, e: string) => {
      const sp = new URLSearchParams(params.toString());
      sp.set("start", s);
      sp.set("end", e);
      // When the user picks a real range, force mode=custom so the
      // dashboard knows to use it; the existing ?date= becomes
      // ignored in custom mode.
      sp.set("mode", "custom");
      sp.delete("date");
      const qs = sp.toString();
      router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  const clear = useCallback(() => {
    const sp = new URLSearchParams(params.toString());
    sp.delete("start");
    sp.delete("end");
    // Drop the custom mode flag too — back to whatever preset the user
    // had before (default: daily).
    if (sp.get("mode") === "custom") sp.delete("mode");
    const qs = sp.toString();
    router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }, [params, pathname, router]);

  return useMemo(
    () => ({ start, end, setRange, clear }),
    [start, end, setRange, clear],
  );
}
