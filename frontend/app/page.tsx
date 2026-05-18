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
  formatMonthLabel,
  formatWeekRange,
} from "@/lib/format";
import { useDateParam } from "@/lib/useDateParam";
import { useModeParam } from "@/lib/useModeParam";

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

  // Range-derived header label: Weekly = Sun–Sat range, Monthly =
  // calendar-month label, Daily = the chosen full date. All computed
  // client-side so the header doesn't flicker waiting on the API.
  const tabValue =
    mode === "weekly" ? "Weekly" : mode === "monthly" ? "Monthly" : "Daily";
  const headerLabel =
    mode === "weekly"
      ? formatWeekRange(date)
      : mode === "monthly"
        ? formatMonthLabel(date)
        : formatIsoFullDate(date);
  const overviewLabel =
    mode === "weekly"
      ? "Weekly overview"
      : mode === "monthly"
        ? "Monthly overview"
        : isToday
          ? "Today’s overview"
          : "Historic overview";

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
          </div>
        </div>
        <DateTabs
          value={tabValue}
          onChange={(t) =>
            setMode(
              t === "Weekly" ? "weekly" : t === "Monthly" ? "monthly" : "daily",
            )
          }
        />
      </header>

      <PulseBar date={date} mode={mode} />

      <section className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <ArrivalHistogram date={date} mode={mode} />
        <DepartmentRollup date={date} mode={mode} />
      </section>

      <ExceptionsPanel date={date} mode={mode} />
    </main>
  );
}

function DashboardSkeleton() {
  return <main className="mx-auto max-w-[1200px] px-10 py-8" />;
}
