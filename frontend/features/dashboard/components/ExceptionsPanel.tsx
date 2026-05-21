"use client";

import { useMemo, useState } from "react";

import { Panel, PanelHeader } from "@/components/ui/Panel";
import { useTypeAheadFilter } from "@/lib/hooks/useTypeAheadFilter";

import {
  useExceptions,
  type DashboardMode,
  type DashboardRange,
} from "../queries";
import type { ExceptionItem, FilterType } from "../types";

const FILTERS: { value: FilterType; label: string }[] = [
  { value: "all", label: "All" },
  { value: "absent", label: "Absent" },
  { value: "missing_punch", label: "Missing punch" },
  { value: "incomplete_hours", label: "Incomplete hours" },
  { value: "late", label: "Late" },
];

type SubtitleCopy = { singular: string; plural: string };

// Subtitle copy per filter chip, per mode. "today"/"yesterday" framing
// matches the daily query; the weekly variant says "this week".
const SUBTITLE_DAILY: Record<FilterType, SubtitleCopy> = {
  all: { singular: "violation flagged today", plural: "violations flagged today" },
  absent: { singular: "absent Prezlaber today", plural: "absent Prezlabers today" },
  missing_punch: {
    singular: "Prezlaber missing a punch yesterday",
    plural: "Prezlabers missing a punch yesterday",
  },
  incomplete_hours: {
    singular: "Prezlaber short on hours yesterday",
    plural: "Prezlabers short on hours yesterday",
  },
  late: { singular: "late Prezlaber today", plural: "late Prezlabers today" },
  review: { singular: "Prezlaber to review", plural: "Prezlabers to review" },
};

const SUBTITLE_WEEKLY: Record<FilterType, SubtitleCopy> = {
  all: { singular: "violation this week", plural: "violations this week" },
  absent: {
    singular: "Prezlaber absent this week",
    plural: "Prezlabers absent this week",
  },
  missing_punch: {
    singular: "Prezlaber missing a punch this week",
    plural: "Prezlabers missing a punch this week",
  },
  incomplete_hours: {
    singular: "Prezlaber short on hours this week",
    plural: "Prezlabers short on hours this week",
  },
  late: {
    singular: "Prezlaber late this week",
    plural: "Prezlabers late this week",
  },
  review: {
    singular: "Prezlaber to review this week",
    plural: "Prezlabers to review this week",
  },
};

const SUBTITLE_MONTHLY: Record<FilterType, SubtitleCopy> = {
  all: { singular: "violation this month", plural: "violations this month" },
  absent: {
    singular: "Prezlaber absent this month",
    plural: "Prezlabers absent this month",
  },
  missing_punch: {
    singular: "Prezlaber missing a punch this month",
    plural: "Prezlabers missing a punch this month",
  },
  incomplete_hours: {
    singular: "Prezlaber short on hours this month",
    plural: "Prezlabers short on hours this month",
  },
  late: {
    singular: "Prezlaber late this month",
    plural: "Prezlabers late this month",
  },
  review: {
    singular: "Prezlaber to review this month",
    plural: "Prezlabers to review this month",
  },
};

const SUBTITLE_CUSTOM: Record<FilterType, SubtitleCopy> = {
  all: { singular: "violation in range", plural: "violations in range" },
  absent: {
    singular: "Prezlaber absent in range",
    plural: "Prezlabers absent in range",
  },
  missing_punch: {
    singular: "Prezlaber missing a punch in range",
    plural: "Prezlabers missing a punch in range",
  },
  incomplete_hours: {
    singular: "Prezlaber short on hours in range",
    plural: "Prezlabers short on hours in range",
  },
  late: {
    singular: "Prezlaber late in range",
    plural: "Prezlabers late in range",
  },
  review: {
    singular: "Prezlaber to review in range",
    plural: "Prezlabers to review in range",
  },
};

const PAGE_SIZE = 6;

export function ExceptionsPanel({
  date,
  mode = "daily",
  range,
}: {
  date?: string;
  mode?: DashboardMode;
  range?: DashboardRange;
}) {
  const [filter, setFilter] = useState<FilterType>("all");
  const [expanded, setExpanded] = useState(false);
  // Per-row expansion (monthly only). Keyed by `tag:emp_code` so the
  // open/closed state survives polling refreshes — same pattern as
  // EmployeesWeekTable. Daily/weekly rows ignore this set.
  const [openRows, setOpenRows] = useState<Set<string>>(() => new Set());
  // Page-level type-ahead — same hook the Employees tables use. Buffer
  // is global to the page (one hook instance per panel), so users can
  // start typing anywhere to narrow the flag list by name/department.
  const { buffer, clear: clearBuffer } = useTypeAheadFilter();
  const { data, isLoading } = useExceptions(date, mode, range);
  const allItems = data?.items ?? [];
  // Apply tag chip filter first, then type-ahead name/department filter.
  // Memoized because the search runs on every keystroke; on a typical
  // dashboard with ~30 rows it's microseconds, but the habit is cheap.
  const items = useMemo(() => {
    const byTag =
      filter === "all" ? allItems : allItems.filter((i) => i.tag === filter);
    if (!buffer) return byTag;
    const needle = buffer.toLowerCase();
    return byTag.filter(
      (i) =>
        i.name.toLowerCase().includes(needle) ||
        i.department.toLowerCase().includes(needle),
    );
  }, [allItems, filter, buffer]);
  const visible = expanded ? items : items.slice(0, PAGE_SIZE);

  const toggleRow = (key: string) => {
    setOpenRows((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const subtitleTable =
    mode === "monthly"
      ? SUBTITLE_MONTHLY
      : mode === "weekly"
        ? SUBTITLE_WEEKLY
        : mode === "custom"
          ? SUBTITLE_CUSTOM
          : SUBTITLE_DAILY;
  const subtitleCopy = subtitleTable[filter];
  const subtitle = `${items.length} ${
    items.length === 1 ? subtitleCopy.singular : subtitleCopy.plural
  }`;

  return (
    <Panel>
      <PanelHeader
        title="Flags"
        subtitle={subtitle}
        right={
          <div className="flex gap-1">
            {FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                onClick={() => setFilter(f.value)}
                className={`rounded-xl px-[10px] py-[4px] text-[11px] ${
                  filter === f.value
                    ? "bg-bg-muted font-medium text-text-primary"
                    : "text-text-tertiary"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        }
      />

      {/* Active type-ahead chip. Only rendered when the buffer has
          content so the panel stays uncluttered in the common case. */}
      {buffer && (
        <div className="flex items-center justify-between border-b border-border bg-bg-subtle px-[18px] py-[8px] text-[12px] text-text-secondary">
          <span>
            Showing {items.length} of {allItems.length} matching “{buffer}”
          </span>
          <button
            type="button"
            onClick={clearBuffer}
            className="flex items-center gap-2 rounded-md bg-bg-muted px-[10px] py-[4px] text-[11px] font-medium text-text-primary"
            title="Click or press Esc to clear"
          >
            <span>Filter: “{buffer}”</span>
            <span className="text-text-tertiary">×</span>
          </button>
        </div>
      )}

      {isLoading && (
        <div className="p-[18px] text-[12px] text-text-tertiary">Loading…</div>
      )}
      {!isLoading && items.length === 0 && (
        <div className="p-[18px] text-[12px] text-text-tertiary">
          {buffer
            ? `No flags match “${buffer}”.`
            : "Nothing to flag right now."}
        </div>
      )}

      {visible.map((item) => {
        const key = `${item.tag}:${item.emp_code}`;
        // Rows are expandable whenever the backend emitted occurrences.
        // That signal already matches "monthly visual treatment" — the
        // backend emits occurrences exactly when chips are suppressed
        // (monthly mode + custom ranges > 7 days). Daily and weekly
        // rows have `occurrences == null` and stay static.
        const expandable =
          item.occurrences != null && item.occurrences.length > 0;
        return (
          <ExceptionRow
            key={key}
            item={item}
            expandable={expandable}
            isOpen={expandable && openRows.has(key)}
            onToggle={expandable ? () => toggleRow(key) : undefined}
          />
        );
      })}

      {items.length > PAGE_SIZE && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="w-full bg-bg-subtle px-[18px] py-[11px] text-[12px] text-text-secondary"
        >
          {expanded
            ? "Show less"
            : `Showing ${PAGE_SIZE} of ${items.length} · View all`}
        </button>
      )}
    </Panel>
  );
}

function ExceptionRow({
  item,
  expandable = false,
  isOpen = false,
  onToggle,
}: {
  item: ExceptionItem;
  expandable?: boolean;
  isOpen?: boolean;
  onToggle?: () => void;
}) {
  const dotColor =
    item.severity === "high"
      ? "bg-severity-high"
      : item.severity === "medium"
        ? "bg-severity-med"
        : "bg-severity-low";

  // Weekly rows carry a `days` list (e.g. ["Mon", "Wed"]). Daily and
  // monthly rows don't, so the chip strip is hidden entirely.
  const dayChips = item.days && item.days.length > 0 ? item.days : null;

  const rowBody = (
    <>
      <div className={`h-[6px] w-[6px] shrink-0 rounded-full ${dotColor}`} />
      <div className="min-w-0 flex-1">
        <p className="m-0 text-[13px] font-medium">
          {item.name}{" "}
          <span className="font-normal text-text-secondary">
            · {item.department}
          </span>
        </p>
        <div className="mt-[2px] flex flex-wrap items-center gap-[6px] text-[12px] text-text-secondary">
          <span>{item.detail}</span>
          {dayChips && (
            <span className="flex flex-wrap gap-[4px]">
              {dayChips.map((d) => (
                <span
                  key={d}
                  className="rounded bg-bg-muted px-[6px] py-[1px] text-[10px] font-medium text-text-secondary"
                >
                  {d}
                </span>
              ))}
            </span>
          )}
        </div>
      </div>
      <Tag tag={item.tag} />
    </>
  );

  // Edge's axe lint flags any JSX expression on aria-expanded as a false
  // positive — passing it via spread satisfies the rule while React
  // still serializes the boolean to the correct DOM attribute.
  const ariaProps: { "aria-expanded": boolean } = { "aria-expanded": isOpen };

  return (
    <div className="border-b border-border">
      {expandable ? (
        <button
          type="button"
          onClick={onToggle}
          {...ariaProps}
          className={`flex w-full items-center gap-[14px] px-[18px] py-[14px] text-left transition-colors hover:bg-bg-subtle ${
            isOpen ? "bg-bg-subtle" : ""
          }`}
        >
          {rowBody}
        </button>
      ) : (
        <div className="flex items-center gap-[14px] px-[18px] py-[14px]">
          {rowBody}
        </div>
      )}
      {expandable && isOpen && item.occurrences && (
        <ExceptionOccurrencesTable
          tag={item.tag}
          occurrences={item.occurrences}
        />
      )}
    </div>
  );
}

function ExceptionOccurrencesTable({
  tag,
  occurrences,
}: {
  tag: ExceptionItem["tag"];
  occurrences: NonNullable<ExceptionItem["occurrences"]>;
}) {
  // Matches the EmployeesWeekTable expanded-child layout: spacer on the
  // left (~7.5% of panel width) so the inner table sits visually nested
  // under its parent row.
  return (
    <div className="flex border-t border-border">
      <div className="w-[7.5%] shrink-0" />
      <table className="flex-1 text-[13px]">
        <thead className="bg-bg-subtle text-[11px] uppercase tracking-[0.04em] text-text-secondary">
          <tr>
            <th className="px-[18px] py-[10px] text-left font-medium">Date</th>
            <th className="px-[18px] py-[10px] text-left font-medium">
              Infraction type
            </th>
            <th className="px-[18px] py-[10px] text-left font-medium">Detail</th>
          </tr>
        </thead>
        <tbody>
          {occurrences.map((o) => (
            <tr
              key={o.date}
              className="border-t border-border hover:bg-bg-subtle"
            >
              <td className="px-[18px] py-[12px] font-mono text-text-secondary">
                {formatIsoAsDdMmYyyy(o.date)}
              </td>
              <td className="px-[18px] py-[12px]">
                <Tag tag={tag} />
              </td>
              <td className="px-[18px] py-[12px] text-text-secondary">
                {o.detail}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// "2026-05-18" → "18-05-2026" per Prezlab's DD-MM-YYYY convention.
function formatIsoAsDdMmYyyy(iso: string): string {
  const [y, m, d] = iso.split("-");
  return `${d}-${m}-${y}`;
}

function Tag({ tag }: { tag: ExceptionItem["tag"] }) {
  const styles: Record<ExceptionItem["tag"], string> = {
    absent: "bg-danger-bg text-danger-text",
    missing_punch: "bg-warning-bg text-warning-text",
    incomplete_hours: "bg-warning-bg text-warning-text",
    late: "bg-warning-bg text-warning-text",
    pattern: "bg-warning-bg text-warning-text",
    review: "bg-bg-muted text-text-secondary",
  };
  const labels: Record<ExceptionItem["tag"], string> = {
    absent: "Absent",
    missing_punch: "Missing punch",
    incomplete_hours: "Incomplete hours",
    late: "Late",
    pattern: "Pattern",
    review: "Review",
  };
  return (
    <span
      className={`rounded px-[9px] py-[3px] text-[11px] font-medium ${styles[tag]}`}
    >
      {labels[tag]}
    </span>
  );
}
