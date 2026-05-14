"use client";

import { Suspense } from "react";

import { DatePickerButton } from "@/components/ui/DatePickerButton";
import { EmployeesTable } from "@/features/employees/components/EmployeesTable";
import { formatIsoFullDate } from "@/lib/format";
import { useDateParam } from "@/lib/useDateParam";

export default function EmployeesPage() {
  return (
    <Suspense fallback={<main className="mx-auto max-w-[1200px] px-10 py-8" />}>
      <EmployeesContent />
    </Suspense>
  );
}

function EmployeesContent() {
  const { date, isToday } = useDateParam();
  return (
    <main className="mx-auto max-w-[1200px] px-10 py-8 pb-12">
      <header className="mb-6">
        <small className="text-[13px] text-text-secondary">
          {isToday ? "Employees" : "Historic employees"}
        </small>
        <div className="mt-1 flex items-center gap-3">
          <h1 className="text-[22px] font-medium">{formatIsoFullDate(date)}</h1>
          <DatePickerButton />
        </div>
      </header>
      <EmployeesTable date={date} />
    </main>
  );
}
