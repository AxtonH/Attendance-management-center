"use client";

import { Suspense } from "react";

import { DatePickerButton } from "@/components/ui/DatePickerButton";
import { DateTabs } from "@/features/dashboard/components/DateTabs";
import { EmployeesTable } from "@/features/employees/components/EmployeesTable";
import { EmployeesWeekTable } from "@/features/employees/components/EmployeesWeekTable";
import { formatIsoFullDate } from "@/lib/format";
import { useDateParam } from "@/lib/useDateParam";
import { useModeParam } from "@/lib/useModeParam";

export default function EmployeesPage() {
  return (
    <Suspense fallback={<main className="mx-auto max-w-[1200px] px-10 py-8" />}>
      <EmployeesContent />
    </Suspense>
  );
}

function EmployeesContent() {
  const { date, isToday } = useDateParam();
  const { mode, setMode } = useModeParam();
  const tabValue = mode === "weekly" ? "Weekly" : "Daily";

  return (
    <main className="mx-auto max-w-[1200px] px-10 py-8 pb-12">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <small className="text-[13px] text-text-secondary">
            {mode === "weekly"
              ? "Employees this week"
              : isToday
                ? "Employees"
                : "Historic employees"}
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
      {mode === "weekly" ? (
        <EmployeesWeekTable date={date} />
      ) : (
        <EmployeesTable date={date} />
      )}
    </main>
  );
}
