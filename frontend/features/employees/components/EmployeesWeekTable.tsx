"use client";

import { useMemo, useState } from "react";

import { Panel, PanelHeader } from "@/components/ui/Panel";
import { formatTime, formatWorkedMinutes } from "@/lib/format";
import { useTypeAheadFilter } from "@/lib/hooks/useTypeAheadFilter";

import { useEmployeesWeek } from "../queries";
import type { EmployeeWeek } from "../types";

// Renders one expandable row per employee with 1+ punches in the week.
// Each row's collapse state is local React state — keyed by emp_code so
// expanded employees survive across re-renders (e.g. when polling pulls
// fresh data) without lifting state to the parent.
export function EmployeesWeekTable({ date }: { date?: string }) {
  const { data, isLoading } = useEmployeesWeek(date);
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
        title="Employees this week"
        subtitle={`${rows.length} of ${data?.rows.length ?? 0} shown`}
        right={<FilterChip buffer={buffer} onClear={clear} />}
      />

      {/* Column header strip — matches the daily Employees table styling
          (bg-bg-subtle + uppercase tracking) so the two views feel like
          siblings, not different products. */}
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
          {buffer
            ? `No employee matches “${buffer}”.`
            : "No punches recorded this week."}
        </p>
      )}
      {rows.map((row) => (
        <EmployeeWeekRow
          key={row.emp_code}
          row={row}
          isExpanded={expanded.has(row.emp_code)}
          onToggle={() => toggle(row.emp_code)}
        />
      ))}
    </Panel>
  );
}

function EmployeeWeekRow({
  row,
  isExpanded,
  onToggle,
}: {
  row: EmployeeWeek;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const daysLabel = row.days_worked === 1 ? "1 day" : `${row.days_worked} days`;
  // Highlight under-expected hours in warning tone. We only have an
  // expected denominator when the backend has schedule data (i.e. Odoo
  // configured); otherwise expected_minutes is 0 and we hide the slash.
  const hasExpected = row.expected_minutes > 0;
  const underHours =
    hasExpected && row.total_worked_minutes < row.expected_minutes;
  // Edge's axe lint flags any JSX expression on aria-expanded because it
  // can't statically resolve the value — false positive. React serializes
  // the boolean to the correct "true"/"false" attribute at runtime. The
  // workaround is to pass the prop via a spread so the rule sees an
  // object spread, not an attribute-with-expression.
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
        <Chevron open={isExpanded} />
        <span className="font-mono text-text-secondary">{row.emp_code}</span>
        <span className="truncate font-medium">{row.name}</span>
        <span className="tabular-nums">
          <span className="text-text-secondary">{daysLabel} · </span>
          <span className={underHours ? "text-warning-text" : "text-text-primary"}>
            {formatWorkedMinutes(row.total_worked_minutes)}
          </span>
          {hasExpected && (
            <span className="text-text-tertiary">
              {" "}/ {formatWorkedMinutes(row.expected_minutes)}
            </span>
          )}
        </span>
      </button>
      {isExpanded && <EmployeeWeekDaysTable days={row.days} />}
    </div>
  );
}

function EmployeeWeekDaysTable({ days }: { days: EmployeeWeek["days"] }) {
  // Mirrors the daily EmployeesTable styling so the two views feel like
  // the same product. The flex+ml-auto wrapper pushes the table to the
  // right edge of the panel so the natural empty space (table cols are
  // tighter than the parent row) sits on the LEFT — reading direction
  // hits the column headers immediately, not whitespace.
  return (
    <div className="flex border-t border-border">
      {/* Spacer cap on the left: pushes the table rightward by ~7.5%
          of the panel width so the data reads weighted-right without
          a large empty band before it. */}
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
                {formatWorkedMinutes(d.worked_minutes)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// "Sun · 10 May" — short weekday + day-month so the row reads cleanly
// even when the user is viewing a week that crosses month boundaries.
function formatWeekdayDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const local = new Date(y, m - 1, d);
  return local.toLocaleDateString("en-GB", {
    weekday: "short",
    day: "2-digit",
    month: "short",
  });
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      className={`shrink-0 text-text-tertiary transition-transform ${
        open ? "rotate-90" : ""
      }`}
      aria-hidden
    >
      <path
        d="M4 2.5L8 6L4 9.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
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
