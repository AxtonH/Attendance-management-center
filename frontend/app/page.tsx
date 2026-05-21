"use client";

import { Suspense } from "react";

import { DatePickerButton } from "@/components/ui/DatePickerButton";
import { ArrivalHistogram } from "@/features/dashboard/components/ArrivalHistogram";
import { DateTabs } from "@/features/dashboard/components/DateTabs";
import { DepartmentRollup } from "@/features/dashboard/components/DepartmentRollup";
import { ExceptionsPanel } from "@/features/dashboard/components/ExceptionsPanel";
import { PulseBar } from "@/features/dashboard/components/PulseBar";
import {
  formatIsoFullDate,
  formatIsoRange,
  formatMonthLabel,
  formatWeekRange,
} from "@/lib/format";
import { useDateParam } from "@/lib/useDateParam";
import { useModeParam } from "@/lib/useModeParam";
import { useRangeParam } from "@/lib/useRangeParam";

// Suspense wrapper: useSearchParams (inside useDateParam/useModeParam) requires
// it so Next.js can prerender the static shell and hydrate the URL-driven bits.
export default function DashboardPage() {
  return (
    <Suspense fallback={<DashboardSkeleton />}>
      <DashboardContent />
    </Suspense>
  );
}

function DashboardContent() {
  const { date, isToday } = useDateParam();
  const { mode, setMode } = useModeParam();
  const { start, end, clear: clearRange } = useRangeParam();

  // Treat custom mode as valid only when both range edges are present.
  // A stale `?mode=custom` without start/end falls back to daily so the
  // dashboard renders something meaningful.
  const effectiveMode =
    mode === "custom" && start && end && start !== end ? "custom" : mode;

  // Range-derived header label.
  const tabValue =
    effectiveMode === "weekly"
      ? "Weekly"
      : effectiveMode === "monthly"
        ? "Monthly"
        : "Daily";

  const headerLabel =
    effectiveMode === "custom" && start && end
      ? formatIsoRange(start, end)
      : effectiveMode === "weekly"
        ? formatWeekRange(date)
        : effectiveMode === "monthly"
          ? formatMonthLabel(date)
          : formatIsoFullDate(date);

  const overviewLabel =
    effectiveMode === "custom"
      ? "Custom range overview"
      : effectiveMode === "weekly"
        ? "Weekly overview"
        : effectiveMode === "monthly"
          ? "Monthly overview"
          : isToday
            ? "Today’s overview"
            : "Historic overview";

  // When user clicks a preset tab while a custom range is active, drop
  // the range so the preset's own date logic takes over.
  const onTabChange = (t: "Daily" | "Weekly" | "Monthly") => {
    if (effectiveMode === "custom") clearRange();
    setMode(t === "Weekly" ? "weekly" : t === "Monthly" ? "monthly" : "daily");
  };

  // Range object passed down to data hooks — only meaningful when mode
  // is custom, but always defined so the prop signature stays simple.
  const range = { start, end };

  return (
    <main className="mx-auto max-w-[1200px] px-10 py-8 pb-12">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <small className="text-[13px] text-text-secondary">
            {overviewLabel}
          </small>
          <div className="mt-1 flex items-center gap-3">
            <h1 className="text-[22px] font-medium">{headerLabel}</h1>
            <DatePickerButton />
            {/* Active-range chip: only when custom mode is engaged.
                Click × to clear, snapping back to the previous preset
                (defaults to daily). */}
            {effectiveMode === "custom" && (
              <button
                type="button"
                onClick={clearRange}
                className="flex items-center gap-2 rounded-md bg-bg-muted px-[10px] py-[4px] text-[12px] font-medium text-text-primary"
                title="Clear custom range"
              >
                <span>Custom range</span>
                <span className="text-text-tertiary">×</span>
              </button>
            )}
          </div>
        </div>
        <DateTabs value={tabValue} onChange={onTabChange} />
      </header>

      <PulseBar date={date} mode={effectiveMode} range={range} />

      <section className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <ArrivalHistogram date={date} mode={effectiveMode} range={range} />
        <DepartmentRollup date={date} mode={effectiveMode} range={range} />
      </section>

      <ExceptionsPanel date={date} mode={effectiveMode} range={range} />
    </main>
  );
}

function DashboardSkeleton() {
  return <main className="mx-auto max-w-[1200px] px-10 py-8" />;
}
