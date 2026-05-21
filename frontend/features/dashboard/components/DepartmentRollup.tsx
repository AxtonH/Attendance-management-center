"use client";

import { SidePanel } from "@/components/ui/Panel";

import {
  useDepartments,
  type DashboardMode,
  type DashboardRange,
} from "../queries";
import type { DepartmentRollup as DepartmentRollupItem } from "../types";

export function DepartmentRollup({
  date,
  mode = "daily",
  range,
}: {
  date?: string;
  mode?: DashboardMode;
  range?: DashboardRange;
}) {
  const { data, isLoading } = useDepartments(date, mode, range);
  const rows = data?.departments ?? [];

  // Empty list → either Odoo isn't configured (phase-1 mode) or every
  // department has zero expected today (e.g. weekend). Either way, show
  // the same friendly placeholder so the panel slot is never blank.
  if (!isLoading && rows.length === 0) {
    return (
      <SidePanel label="Department roll-up">
        <div className="flex flex-1 flex-col items-start justify-center gap-2 py-4">
          <p className="m-0 text-[13px] font-medium text-text-primary">
            Nothing to roll up today
          </p>
          <p className="m-0 text-[12px] text-text-tertiary">
            No departments have scheduled attendance for this day.
          </p>
        </div>
      </SidePanel>
    );
  }

  return (
    <SidePanel label="Department roll-up">
      <ul className="m-0 flex flex-1 list-none flex-col gap-0 p-0">
        {isLoading && (
          <li className="py-2 text-[12px] text-text-tertiary">Loading…</li>
        )}
        {rows.map((row) => (
          <DepartmentRow key={row.name} row={row} />
        ))}
      </ul>
    </SidePanel>
  );
}

function DepartmentRow({ row }: { row: DepartmentRollupItem }) {
  const hasAbsent = row.absent > 0;
  const hasLate = row.late > 0;
  // Absent is more severe than late, so a row with absents goes red even
  // if it also has lates. Late-only stays orange. No flags → muted grey.
  const tone = hasAbsent
    ? "text-danger-text"
    : hasLate
      ? "text-warning-text"
      : "text-text-tertiary";
  return (
    <li className="flex items-center justify-between py-[5px] text-[13px]">
      <span className="truncate pr-2 text-text-primary">{row.name}</span>
      <span className={`shrink-0 tabular-nums ${tone}`}>
        {row.present} / {row.expected}
        {hasAbsent && <span> · {row.absent} absent</span>}
        {hasLate && <span> · {row.late} late</span>}
      </span>
    </li>
  );
}
