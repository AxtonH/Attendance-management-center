"use client";

import { Suspense } from "react";

import { DatePickerButton } from "@/components/ui/DatePickerButton";
import { ArrivalHistogram } from "@/features/dashboard/components/ArrivalHistogram";
import { DateTabs } from "@/features/dashboard/components/DateTabs";
import { DepartmentRollup } from "@/features/dashboard/components/DepartmentRollup";
import { ExceptionsPanel } from "@/features/dashboard/components/ExceptionsPanel";
import { PulseBar } from "@/features/dashboard/components/PulseBar";
import { formatIsoFullDate } from "@/lib/format";
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

  // Weekly displays the week containing `date` (Sun–Sat, see week_range_for
  // on the backend). The backend echoes range_start/end on the response, but
  // we can compute the label client-side too; using formatIsoFullDate(date)
  // keeps the header tight while showing what anchor day the user picked.
  const tabValue = mode === "weekly" ? "Weekly" : "Daily";

  return (
    <main className="mx-auto max-w-[1200px] px-10 py-8 pb-12">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <small className="text-[13px] text-text-secondary">
            {mode === "weekly"
              ? "Weekly overview"
              : isToday
                ? "Today’s overview"
                : "Historic overview"}
          </small>
          <div className="mt-1 flex items-center gap-3">
            <h1 className="text-[22px] font-medium">{formatIsoFullDate(date)}</h1>
            <DatePickerButton />
          </div>
        </div>
        <DateTabs
          value={tabValue}
          onChange={(t) => setMode(t === "Weekly" ? "weekly" : "daily")}
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
