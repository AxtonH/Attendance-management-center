"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useMemo } from "react";

export type DashboardMode = "daily" | "weekly" | "monthly";

const VALID: ReadonlySet<DashboardMode> = new Set([
  "daily",
  "weekly",
  "monthly",
]);

/**
 * Read & write the ?mode=daily|weekly URL query param.
 *
 * Defaults to "daily" when the param is missing or malformed. Setting
 * "daily" removes the param entirely so the URL stays clean for the
 * common case (mirrors the useDateParam pattern).
 *
 * Preserves all other search params on change so flipping the tab
 * doesn't drop the active ?date=.
 */
export function useModeParam(): {
  mode: DashboardMode;
  setMode: (next: DashboardMode) => void;
} {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const raw = params.get("mode");
  const mode: DashboardMode = VALID.has(raw as DashboardMode)
    ? (raw as DashboardMode)
    : "daily";

  const setMode = useCallback(
    (next: DashboardMode) => {
      const sp = new URLSearchParams(params.toString());
      if (next === "daily") {
        sp.delete("mode");
      } else {
        sp.set("mode", next);
      }
      const qs = sp.toString();
      router.push(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [params, pathname, router],
  );

  return useMemo(() => ({ mode, setMode }), [mode, setMode]);
}
