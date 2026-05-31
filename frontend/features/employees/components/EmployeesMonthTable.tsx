"use client";

import { useMemo, useState } from "react";

import { Panel, PanelHeader } from "@/components/ui/Panel";
import {
  formatTime,
  formatWeekRange,
  formatWorkedMinutes,
  weekRangeFor,
} from "@/lib/format";
import { useTypeAheadFilter } from "@/lib/hooks/useTypeAheadFilter";

import { useEmployeesMonth, useEmployeesRange } from "../queries";
import type { EmployeeWeek, EmployeeWeekDay, EmployeesMonth } from "../types";
import { AbsentPill, OnLeavePill } from "./AbsentPill";

// Monthly variant of EmployeesWeekTable. The per-employee row shape is
// identical (we reuse the EmployeeWeek type), but the child table groups
// the punched days into Sunday-anchored week sections so a 20-row table
// scans like a small calendar instead of a flat list. The header drops
// the `/ expected hours` denominator since a calendar month has no
// fixed target (variable length, holidays, etc.).
//
// The custom-range variant (EmployeesRangeTable, below) renders the
// exact same body — it just feeds a different data hook in. Keeping
// both wrappers in this file lets the inner pieces stay private.

export function EmployeesMonthTable({ date }: { date?: string }) {
  const { data, isLoading } = useEmployeesMonth(date);
  return (
    <EmployeesRangeBody
      data={data}
      isLoading={isLoading}
      title="Employees this month"
      emptyText="No punches recorded this month."
    />
  );
}

export function EmployeesRangeTable({
  start,
  end,
}: {
  start: string | null;
  end: string | null;
}) {
  const { data, isLoading } = useEmployeesRange(start, end);
  return (
    <EmployeesRangeBody
      data={data}
      isLoading={isLoading}
      title="Employees in range"
      emptyText="No punches recorded in this range."
    />
  );
}

function EmployeesRangeBody({
  data,
  isLoading,
  title,
  emptyText,
}: {
  data: EmployeesMonth | undefined;
  isLoading: boolean;
  title: string;
  emptyText: string;
}) {
  const { buffer, clear } = useTypeAheadFilter();
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  const rows = useMemo(() => {
    const all = data?.rows ?? [];
    if (!buffer) return all;
    const needle = buffer.toLowerCase();
    return all.filter((r) => r.name.toLowerCase().includes(needle));
  }, [data, buffer]);

  const toggle = (code: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  return (
    <Panel>
      <PanelHeader
        title={title}
        subtitle={`${rows.length} of ${data?.rows.length ?? 0} shown`}
        right={<FilterChip buffer={buffer} onClear={clear} />}
      />

      {/* Same column header strip as weekly — keeps the two views looking
          like siblings. */}
      <div className="grid grid-cols-[24px_72px_1fr_auto] items-center gap-[14px] border-b border-border bg-bg-subtle px-[18px] py-[10px] text-[11px] uppercase tracking-[0.04em] text-text-secondary">
        <span aria-hidden />
        <span>Emp code</span>
        <span>Name</span>
        <span>Days worked · Hours</span>
      </div>

      {isLoading && (
        <p className="px-[18px] py-6 text-center text-[13px] text-text-tertiary">
          Loading…
        </p>
      )}
      {!isLoading && rows.length === 0 && (
        <p className="px-[18px] py-6 text-center text-[13px] text-text-tertiary">
          {buffer ? `No employee matches “${buffer}”.` : emptyText}
        </p>
      )}
      {rows.map((row) => (
        <EmployeeMonthRow
          key={row.emp_code}
          row={row}
          isExpanded={expanded.has(row.emp_code)}
          onToggle={() => toggle(row.emp_code)}
        />
      ))}
    </Panel>
  );
}

function EmployeeMonthRow({
  row,
  isExpanded,
  onToggle,
}: {
  row: EmployeeWeek;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const daysLabel = row.days_worked === 1 ? "1 day" : `${row.days_worked} days`;
  // Edge's axe lint flags any JSX expression on aria-expanded as a false
  // positive — passing it via spread satisfies the rule while React
  // still serializes the boolean to the correct DOM attribute.
  const ariaProps: { "aria-expanded": boolean } = { "aria-expanded": isExpanded };

  return (
    <div className="border-t border-border">
      <button
        type="button"
        onClick={onToggle}
        {...ariaProps}
        className={`grid w-full grid-cols-[24px_72px_1fr_auto] items-center gap-[14px] px-[18px] py-[12px] text-left text-[13px] transition-colors hover:bg-bg-subtle ${
          isExpanded ? "bg-bg-subtle" : ""
        }`}
      >
        <span aria-hidden />
        <span className="font-mono text-text-secondary">{row.emp_code}</span>
        <span className="truncate font-medium">{row.name}</span>
        <span className="tabular-nums">
          <span className="text-text-secondary">{daysLabel} · </span>
          <span className="text-text-primary">
            {formatWorkedMinutes(row.total_worked_minutes)}
          </span>
        </span>
      </button>
      {isExpanded && <EmployeeMonthDaysTable days={row.days} />}
    </div>
  );
}

function EmployeeMonthDaysTable({ days }: { days: EmployeeWeek["days"] }) {
  // Group child rows by the Sun-anchored week containing each day. We
  // memoize because the grouping is non-trivial and the same `days`
  // reference is stable across re-renders inside the expansion.
  const weeks = useMemo(() => groupByWeek(days), [days]);

  return (
    <div className="flex border-t border-border">
      {/* Same 7.5% left spacer as the weekly view so the child table
          visually nests under its parent row. */}
      <div className="w-[7.5%] shrink-0" />
      <table className="flex-1 text-[13px]">
        <thead className="bg-bg-subtle text-[11px] uppercase tracking-[0.04em] text-text-secondary">
          <tr>
            <th className="px-[18px] py-[10px] text-left font-medium">Day</th>
            <th className="px-[18px] py-[10px] text-left font-medium">Punch in</th>
            <th className="px-[18px] py-[10px] text-left font-medium">Punch out</th>
            <th className="px-[18px] py-[10px] text-left font-medium">Worked time</th>
          </tr>
        </thead>
        <tbody>
          {weeks.map((week) => (
            <WeekSection
              key={week.headerIso}
              headerIso={week.headerIso}
              days={week.days}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WeekSection({
  headerIso,
  days,
}: {
  headerIso: string;
  days: EmployeeWeekDay[];
}) {
  return (
    <>
      <tr className="border-t border-border bg-bg-subtle/60">
        <td
          colSpan={4}
          className="px-[18px] py-[6px] text-[11px] font-medium uppercase tracking-[0.04em] text-text-tertiary"
        >
          Week of {formatWeekRange(headerIso)}
        </td>
      </tr>
      {days.map((d) => (
        <tr
          key={d.date}
          className="border-t border-border hover:bg-bg-subtle"
        >
          <td className="px-[18px] py-[12px] font-mono text-text-secondary">
            {formatWeekdayDate(d.date)}
          </td>
          <td className="px-[18px] py-[12px] text-text-secondary">
            {formatTime(d.punch_in)}
          </td>
          <td className="px-[18px] py-[12px] text-text-secondary">
            {formatTime(d.punch_out)}
          </td>
          <td className="px-[18px] py-[12px] text-text-secondary tabular-nums">
            {d.on_leave ? (
              <OnLeavePill />
            ) : d.absent ? (
              <AbsentPill />
            ) : (
              formatWorkedMinutes(d.worked_minutes)
            )}
          </td>
        </tr>
      ))}
    </>
  );
}

// Bucket a chronological list of days into Sunday-anchored weeks. We
// only include days that are actually in the input (partial weeks at
// month edges show fewer rows — matches the "show only days inside the
// month" decision). The header date is the week's Sunday so a single
// formatWeekRange() call renders the full range label.
function groupByWeek(
  days: EmployeeWeekDay[],
): { headerIso: string; days: EmployeeWeekDay[] }[] {
  const buckets: { headerIso: string; days: EmployeeWeekDay[] }[] = [];
  for (const d of days) {
    const sunday = weekRangeFor(d.date).start;
    const headerIso = toIso(sunday);
    const last = buckets[buckets.length - 1];
    if (last && last.headerIso === headerIso) {
      last.days.push(d);
    } else {
      buckets.push({ headerIso, days: [d] });
    }
  }
  return buckets;
}

function toIso(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function formatWeekdayDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const local = new Date(y, m - 1, d);
  return local.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
  });
}

function FilterChip({ buffer, onClear }: { buffer: string; onClear: () => void }) {
  if (!buffer) {
    return (
      <span className="text-[11px] text-text-tertiary">
        Start typing to filter by name
      </span>
    );
  }
  return (
    <button
      type="button"
      onClick={onClear}
      className="flex items-center gap-2 rounded-md bg-bg-muted px-[10px] py-[4px] text-[12px] font-medium text-text-primary"
      title="Click or press Esc to clear"
    >
      <span>Filter: “{buffer}”</span>
      <span className="text-text-tertiary">×</span>
    </button>
  );
}
