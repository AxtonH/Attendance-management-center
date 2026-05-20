"use client";

import { Suspense } from "react";

import { DatePickerButton } from "@/components/ui/DatePickerButton";
import { DateTabs } from "@/features/dashboard/components/DateTabs";
import { EmployeesMonthTable } from "@/features/employees/components/EmployeesMonthTable";
import { EmployeesTable } from "@/features/employees/components/EmployeesTable";
import { EmployeesWeekTable } from "@/features/employees/components/EmployeesWeekTable";
import {
  formatIsoFullDate,
  formatMonthLabel,
  formatWeekRange,
} from "@/lib/format";
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
  // Range-derived header text. Computed client-side so the page reads
  // correctly without waiting on the API.
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
      ? "Employees this week"
      : mode === "monthly"
        ? "Employees this month"
        : isToday
          ? "Employees"
          : "Historic employees";

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
      {mode === "monthly" ? (
        <EmployeesMonthTable date={date} />
      ) : mode === "weekly" ? (
        <EmployeesWeekTable date={date} />
      ) : (
        <EmployeesTable date={date} />
      )}
    </main>
  );
}
