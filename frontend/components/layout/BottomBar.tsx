"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

// "Last sync" is derived from the most-recent successful query update across
// the React Query cache. Avoids the need for a separate sync timestamp.
function useLastSyncMinutes(): number | null {
  const qc = useQueryClient();
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const interval = setInterval(() => setTick((t) => t + 1), 15_000);
    return () => clearInterval(interval);
  }, []);

  const latest = qc
    .getQueryCache()
    .findAll()
    .map((q) => q.state.dataUpdatedAt)
    .filter((t) => t > 0)
    .reduce((max, t) => Math.max(max, t), 0);

  if (latest === 0) return null;
  void tick;
  return Math.floor((Date.now() - latest) / 60_000);
}

export function BottomBar() {
  const mins = useLastSyncMinutes();
  const label =
    mins === null
      ? "Connecting to Biotime…"
      : mins < 1
        ? "Connected to Biotime · Last sync just now"
        : `Connected to Biotime · Last sync ${mins} min ago`;

  return (
    <div className="flex items-center justify-between bg-bg-dark px-10 py-[18px] text-[12px] text-text-on-dark-muted">
      <div className="flex items-center gap-2">
        <div className="h-[7px] w-[7px] rounded-full bg-emerald-400" />
        <span>{label}</span>
      </div>
      <div className="flex gap-5">
        <span className="cursor-pointer">Documentation</span>
        <span className="cursor-pointer">Support</span>
        <span>v1.0</span>
      </div>
    </div>
  );
}
