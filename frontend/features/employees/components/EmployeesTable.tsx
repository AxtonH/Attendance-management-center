"use client";

import { useMemo } from "react";

import { Panel, PanelHeader } from "@/components/ui/Panel";
import { formatTime, formatWorkedMinutes } from "@/lib/format";
import { useTypeAheadFilter } from "@/lib/hooks/useTypeAheadFilter";

import { useEmployeesToday } from "../queries";
import type { EmployeeDay } from "../types";
import { AbsentPill, HolidayPill, OnLeavePill } from "./AbsentPill";

function sortRows(rows: EmployeeDay[]): EmployeeDay[] {
  // emp_code descending. Numeric where possible, lexical as a fallback.
  return [...rows].sort((a, b) => {
    const na = Number(a.emp_code);
    const nb = Number(b.emp_code);
    if (!Number.isNaN(na) && !Number.isNaN(nb)) return nb - na;
    return b.emp_code.localeCompare(a.emp_code);
  });
}

export function EmployeesTable({ date }: { date?: string }) {
  const { data, isLoading } = useEmployeesToday(date);
  const { buffer, clear } = useTypeAheadFilter();

  const rows = useMemo(() => {
    const all = sortRows(data?.rows ?? []);
    if (!buffer) return all;
    const needle = buffer.toLowerCase();
    return all.filter((r) => r.name.toLowerCase().includes(needle));
  }, [data, buffer]);

  return (
    <Panel>
      <PanelHeader
        title="Employees today"
        subtitle={`${rows.length} of ${data?.rows.length ?? 0} shown`}
        right={<FilterChip buffer={buffer} onClear={clear} />}
      />
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead className="bg-bg-subtle text-[11px] uppercase tracking-[0.04em] text-text-secondary">
            <tr>
              <th className="px-[18px] py-[10px] text-left font-medium">Emp code</th>
              <th className="px-[18px] py-[10px] text-left font-medium">Name</th>
              <th className="px-[18px] py-[10px] text-left font-medium">Punch in</th>
              <th className="px-[18px] py-[10px] text-left font-medium">Punch out</th>
              <th className="px-[18px] py-[10px] text-left font-medium">Worked time</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr>
                <td colSpan={5} className="px-[18px] py-6 text-center text-text-tertiary">
                  Loading…
                </td>
              </tr>
            )}
            {!isLoading && rows.length === 0 && (
              <tr>
                <td colSpan={5} className="px-[18px] py-6 text-center text-text-tertiary">
                  {buffer ? `No employee matches “${buffer}”.` : "No punches yet today."}
                </td>
              </tr>
            )}
            {rows.map((r) => (
              <tr
                key={r.emp_code}
                className="border-t border-border hover:bg-bg-subtle"
              >
                <td className="px-[18px] py-[12px] font-mono text-text-secondary">
                  {r.emp_code}
                </td>
                <td className="px-[18px] py-[12px] font-medium">{r.name}</td>
                <td className="px-[18px] py-[12px] text-text-secondary">
                  {formatTime(r.punch_in)}
                </td>
                <td className="px-[18px] py-[12px] text-text-secondary">
                  {formatTime(r.punch_out)}
                </td>
                <td className="px-[18px] py-[12px] text-text-secondary">
                  {r.on_holiday ? (
                    <HolidayPill />
                  ) : r.on_leave ? (
                    <OnLeavePill />
                  ) : r.absent ? (
                    <AbsentPill />
                  ) : (
                    formatWorkedMinutes(r.worked_minutes)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
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
