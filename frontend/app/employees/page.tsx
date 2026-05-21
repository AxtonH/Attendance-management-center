"use client";

import { Suspense } from "react";

import { DatePickerButton } from "@/components/ui/DatePickerButton";
import { DateTabs } from "@/features/dashboard/components/DateTabs";
import {
  EmployeesMonthTable,
  EmployeesRangeTable,
} from "@/features/employees/components/EmployeesMonthTable";
import { EmployeesTable } from "@/features/employees/components/EmployeesTable";
import { EmployeesWeekTable } from "@/features/employees/components/EmployeesWeekTable";
import {
  formatIsoFullDate,
  formatIsoRange,
  formatMonthLabel,
  formatWeekRange,
} from "@/lib/format";
import { useDateParam } from "@/lib/useDateParam";
import { useModeParam } from "@/lib/useModeParam";
import { useRangeParam } from "@/lib/useRangeParam";

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
  const { start, end, clear: clearRange } = useRangeParam();

  // Treat custom mode as valid only when both range edges are present
  // AND they're different (same-day custom collapses to daily, matching
  // the picker's behavior on the dashboard).
  const effectiveMode =
    mode === "custom" && start && end && start !== end ? "custom" : mode;

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
      ? "Employees in range"
      : effectiveMode === "weekly"
        ? "Employees this week"
        : effectiveMode === "monthly"
          ? "Employees this month"
          : isToday
            ? "Employees"
            : "Historic employees";

  // Clicking a preset tab while custom range is active clears the range
  // so the preset's own date logic takes over — matches dashboard.
  const onTabChange = (t: "Daily" | "Weekly" | "Monthly") => {
    if (effectiveMode === "custom") clearRange();
    setMode(t === "Weekly" ? "weekly" : t === "Monthly" ? "monthly" : "daily");
  };

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
      {effectiveMode === "custom" ? (
        // Custom range uses the same week-grouped layout as monthly —
        // the only difference is which dates feed in.
        <EmployeesRangeTable start={start} end={end} />
      ) : effectiveMode === "monthly" ? (
        <EmployeesMonthTable date={date} />
      ) : effectiveMode === "weekly" ? (
        <EmployeesWeekTable date={date} />
      ) : (
        <EmployeesTable date={date} />
      )}
    </main>
  );
}
