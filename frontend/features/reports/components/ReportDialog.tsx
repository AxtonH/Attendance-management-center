"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  formatIsoFullDate,
  formatIsoRange,
  formatMonthLabel,
  formatWeekRange,
} from "@/lib/format";

import { downloadExport, type ExportFormat, type ReportView } from "../download";
import { useExportRoster } from "../queries";
import type { RosterEmployee } from "../types";

// Employees with no department land in one bucket so the filter still
// covers the whole roster (phase-1 has no department data at all).
const NO_DEPARTMENT = "__none__";

/**
 * The report builder: filter by department, toggle who's included, then
 * export the selection as Excel or PDF. Everyone starts included — the
 * common case ("export the whole team") is two clicks.
 *
 * The department chips *scope the selection* and are multi-select: the
 * report covers the union of active chips. Toggling a chip on pulls that
 * department in (all on); toggling it off drops its people out; manual
 * per-person toggles inside departments that stay active are preserved.
 * No active chips = "All departments" = everyone. Search is different —
 * it only changes what's visible, so you can find one person to toggle
 * without disturbing the rest.
 */
export function ReportDialog({
  view,
  onClose,
}: {
  view: ReportView;
  onClose: () => void;
}) {
  const { data, isLoading, isError, refetch } = useExportRoster(view);
  const employees = useMemo(() => data?.employees ?? [], [data]);

  // Active department chips. Empty = "All departments" (no scoping).
  const [depts, setDepts] = useState<ReadonlySet<string>>(new Set());
  const [query, setQuery] = useState("");
  // Excluded set (not included set): the default "everyone in" needs no
  // state seeding when the roster arrives, and late-loading employees are
  // included automatically.
  const [excluded, setExcluded] = useState<ReadonlySet<string>>(new Set());
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [error, setError] = useState(false);

  const overlayRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  const departments = useMemo(() => {
    const names = new Set<string>();
    let hasUnassigned = false;
    for (const emp of employees) {
      if (emp.department) names.add(emp.department);
      else hasUnassigned = true;
    }
    const sorted = [...names].sort((a, b) => a.localeCompare(b));
    // Only offer "No department" when it's a real subset, i.e. departments
    // exist but some people lack one. Phase-1 (nobody has a department)
    // hides the filter row entirely.
    if (sorted.length > 0 && hasUnassigned) sorted.push(NO_DEPARTMENT);
    return sorted;
  }, [employees]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return employees.filter((emp) => {
      if (!inScope(emp, depts)) return false;
      if (q && !emp.name.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [employees, depts, query]);

  // Chips scope the report to the union of active departments, so the
  // exported file matches what the list shows. Adding a department pulls
  // its people in (fresh, all on); removing one drops its people out.
  // Manual toggles inside departments that stay active are preserved.
  const toggleDept = (d: string) => {
    const wasAll = depts.size === 0;
    const nextDepts = new Set(depts);
    if (nextDepts.has(d)) nextDepts.delete(d);
    else nextDepts.add(d);
    setDepts(nextDepts);

    if (nextDepts.size === 0) {
      // Last chip switched off → back to "All departments" = everyone.
      setExcluded(new Set());
      return;
    }
    setExcluded((prev) => {
      // Entering scoped mode from "All": start from just this department.
      if (wasAll) {
        return new Set(
          employees
            .filter((emp) => !inScope(emp, nextDepts))
            .map((emp) => emp.emp_code),
        );
      }
      const next = new Set(prev);
      const members = employees.filter((emp) => inDepartment(emp, d));
      for (const emp of members) {
        if (nextDepts.has(d)) next.delete(emp.emp_code);
        else next.add(emp.emp_code);
      }
      return next;
    });
  };

  const selectAllDepts = () => {
    setDepts(new Set());
    setExcluded(new Set());
  };

  const selectedCount = employees.length - excluded.size;
  const allSelected = excluded.size === 0;

  const toggle = (code: string) => {
    setExcluded((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  // Bulk actions operate on the *visible* subset so "Select all" inside a
  // department filter means "all of this department".
  const setVisibleSelected = (included: boolean) => {
    setExcluded((prev) => {
      const next = new Set(prev);
      for (const emp of visible) {
        if (included) next.delete(emp.emp_code);
        else next.add(emp.emp_code);
      }
      return next;
    });
  };

  const download = async (format: ExportFormat) => {
    setBusy(format);
    setError(false);
    try {
      const codes = allSelected
        ? null // clean URL: no emp_codes param means "everyone"
        : employees
            .filter((emp) => !excluded.has(emp.emp_code))
            .map((emp) => emp.emp_code);
      await downloadExport(format, view, codes);
      onClose();
    } catch {
      setError(true);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      ref={overlayRef}
      onMouseDown={(e) => {
        if (e.target === overlayRef.current) onClose();
      }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-6"
      role="dialog"
      aria-modal="true"
      aria-label="Export attendance report"
    >
      <div className="flex max-h-[85vh] w-full max-w-[620px] flex-col overflow-hidden rounded-lg bg-bg-surface shadow-2xl">
        {/* Header */}
        <div className="flex items-start justify-between border-b border-border px-6 py-4">
          <div>
            <h2 className="m-0 text-[15px] font-medium text-text-primary">
              Export report
            </h2>
            <p className="mt-[2px] text-[12px] text-text-tertiary">
              {periodLabel(view)}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-md p-1 text-text-tertiary hover:bg-bg-subtle hover:text-text-primary"
          >
            <CloseIcon />
          </button>
        </div>

        {/* Filters */}
        <div className="border-b border-border px-6 py-3">
          {departments.length > 0 && (
            <div className="mb-3 flex flex-wrap gap-[6px]">
              <DeptChip
                label="All departments"
                active={depts.size === 0}
                onClick={selectAllDepts}
              />
              {departments.map((d) => (
                <DeptChip
                  key={d}
                  label={d === NO_DEPARTMENT ? "No department" : d}
                  active={depts.has(d)}
                  onClick={() => toggleDept(d)}
                />
              ))}
            </div>
          )}
          <div className="flex items-center gap-3">
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search employees…"
              className="h-[30px] flex-1 rounded-md border border-border-strong bg-bg-surface px-3 text-[13px] text-text-primary placeholder:text-text-tertiary focus:border-accent focus:outline-none"
            />
            <div className="flex shrink-0 gap-3 text-[12px]">
              <button
                type="button"
                onClick={() => setVisibleSelected(true)}
                className="text-accent hover:underline"
              >
                Select all
              </button>
              <button
                type="button"
                onClick={() => setVisibleSelected(false)}
                className="text-text-tertiary hover:underline"
              >
                Clear
              </button>
            </div>
          </div>
        </div>

        {/* Employee list */}
        <div className="min-h-[180px] flex-1 overflow-y-auto px-3 py-2">
          {isLoading && (
            <p className="px-3 py-6 text-center text-[13px] text-text-tertiary">
              Loading employees…
            </p>
          )}
          {isError && (
            <p className="px-3 py-6 text-center text-[13px] text-danger-text">
              Couldn’t load the employee list.{" "}
              <button
                type="button"
                onClick={() => refetch()}
                className="underline"
              >
                Retry
              </button>
            </p>
          )}
          {!isLoading && !isError && visible.length === 0 && (
            <p className="px-3 py-6 text-center text-[13px] text-text-tertiary">
              No employees match.
            </p>
          )}
          {visible.map((emp) => (
            <EmployeeRow
              key={emp.emp_code}
              employee={emp}
              included={!excluded.has(emp.emp_code)}
              onToggle={() => toggle(emp.emp_code)}
            />
          ))}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border bg-bg-subtle px-6 py-4">
          <p className="m-0 text-[12px] text-text-secondary">
            {selectedCount} of {employees.length} employees included
            {error && (
              <span className="ml-2 text-danger-text">
                Export failed. Try again.
              </span>
            )}
          </p>
          <div className="flex gap-2">
            <FooterButton
              label="PDF"
              busy={busy === "pdf"}
              disabled={busy !== null || selectedCount === 0}
              variant="secondary"
              onClick={() => download("pdf")}
            />
            <FooterButton
              label="Excel"
              busy={busy === "excel"}
              disabled={busy !== null || selectedCount === 0}
              variant="primary"
              onClick={() => download("excel")}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function inDepartment(emp: RosterEmployee, dept: string): boolean {
  if (dept === NO_DEPARTMENT) return !emp.department;
  return emp.department === dept;
}

/** Empty set = "All departments"; otherwise the union of active chips. */
function inScope(emp: RosterEmployee, depts: ReadonlySet<string>): boolean {
  if (depts.size === 0) return true;
  return [...depts].some((d) => inDepartment(emp, d));
}

function periodLabel(view: ReportView): string {
  if (view.mode === "weekly") return formatWeekRange(view.date);
  if (view.mode === "monthly") return formatMonthLabel(view.date);
  if (view.mode === "custom" && view.start && view.end)
    return formatIsoRange(view.start, view.end);
  return formatIsoFullDate(view.date);
}

function DeptChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? "rounded-full bg-bg-dark px-3 py-[4px] text-[12px] text-text-on-dark"
          : "rounded-full border border-border-strong px-3 py-[3px] text-[12px] text-text-secondary hover:border-border-strong hover:text-text-primary"
      }
    >
      {label}
    </button>
  );
}

function EmployeeRow({
  employee,
  included,
  onToggle,
}: {
  employee: RosterEmployee;
  included: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={included}
      onClick={onToggle}
      className="flex w-full items-center gap-3 rounded-md px-3 py-[7px] text-left hover:bg-bg-subtle"
    >
      <Toggle on={included} />
      <span
        className={`flex-1 truncate text-[13px] ${
          included ? "text-text-primary" : "text-text-tertiary"
        }`}
      >
        {employee.name}
      </span>
      {employee.department && (
        <span className="shrink-0 text-[11px] text-text-tertiary">
          {employee.department}
        </span>
      )}
    </button>
  );
}

/** Small pill switch — the include/exclude affordance on each row. */
function Toggle({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden
      className={`relative inline-block h-[16px] w-[28px] shrink-0 rounded-full transition-colors ${
        on ? "bg-accent" : "bg-black/15"
      }`}
    >
      <span
        className={`absolute top-[2px] h-[12px] w-[12px] rounded-full bg-white transition-transform ${
          on ? "translate-x-[14px]" : "translate-x-[2px]"
        }`}
      />
    </span>
  );
}

function FooterButton({
  label,
  busy,
  disabled,
  variant,
  onClick,
}: {
  label: string;
  busy: boolean;
  disabled: boolean;
  variant: "primary" | "secondary";
  onClick: () => void;
}) {
  const base =
    "h-[32px] rounded-md px-4 text-[13px] font-medium disabled:cursor-default disabled:opacity-50";
  const style =
    variant === "primary"
      ? "bg-bg-dark text-text-on-dark hover:bg-black"
      : "border border-border-strong text-text-primary hover:bg-bg-subtle";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${style}`}
    >
      {busy ? "Preparing…" : `Export ${label}`}
    </button>
  );
}

function CloseIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden>
      <path
        d="M3 3L11 11M11 3L3 11"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}
