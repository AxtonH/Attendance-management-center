"use client";

import { Suspense, useState } from "react";

import { DatePickerButton } from "@/components/ui/DatePickerButton";
import { ArrivalHistogram } from "@/features/dashboard/components/ArrivalHistogram";
import { DateTabs } from "@/features/dashboard/components/DateTabs";
import { DepartmentRollup } from "@/features/dashboard/components/DepartmentRollup";
import { ExceptionsPanel } from "@/features/dashboard/components/ExceptionsPanel";
import { PulseBar } from "@/features/dashboard/components/PulseBar";
import { formatIsoFullDate } from "@/lib/format";
import { useDateParam } from "@/lib/useDateParam";

// Suspense wrapper: useSearchParams (inside useDateParam) requires it so
// Next.js can prerender the static shell and hydrate the URL-driven bits.
export default function DashboardPage() {
  return (
    <Suspense fallback={<DashboardSkeleton />}>
      <DashboardContent />
    </Suspense>
  );
}

function DashboardContent() {
  const [tab, setTab] = useState<"Daily" | "Weekly" | "Monthly">("Daily");
  const { date, isToday } = useDateParam();

  return (
    <main className="mx-auto max-w-[1200px] px-10 py-8 pb-12">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <small className="text-[13px] text-text-secondary">
            {isToday ? "Today’s overview" : "Historic overview"}
          </small>
          <div className="mt-1 flex items-center gap-3">
            <h1 className="text-[22px] font-medium">{formatIsoFullDate(date)}</h1>
            <DatePickerButton />
          </div>
        </div>
        <DateTabs value={tab} onChange={setTab} />
      </header>

      <PulseBar date={date} />

      <section className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        <ArrivalHistogram date={date} />
        <DepartmentRollup date={date} />
      </section>

      <ExceptionsPanel date={date} />
    </main>
  );
}

function DashboardSkeleton() {
  return <main className="mx-auto max-w-[1200px] px-10 py-8" />;
}
