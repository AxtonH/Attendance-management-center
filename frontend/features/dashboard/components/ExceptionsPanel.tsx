"use client";

import { useState } from "react";

import { Panel, PanelHeader } from "@/components/ui/Panel";

import { useExceptions } from "../queries";
import type { ExceptionItem, FilterType } from "../types";

const FILTERS: { value: FilterType; label: string }[] = [
  { value: "all", label: "All" },
  { value: "absent", label: "Absent" },
  { value: "missing_punch", label: "Missing punch" },
  { value: "incomplete_hours", label: "Incomplete hours" },
  { value: "late", label: "Late" },
];

// Subtitle copy per filter chip. Singular form lives next to its plural so
// 1-vs-N grammar stays in one table.
const SUBTITLE: Record<
  FilterType,
  { singular: string; plural: string }
> = {
  all: { singular: "violation flagged today", plural: "violations flagged today" },
  absent: {
    singular: "absent Prezlaber today",
    plural: "absent Prezlabers today",
  },
  missing_punch: {
    singular: "Prezlaber missing a punch yesterday",
    plural: "Prezlabers missing a punch yesterday",
  },
  incomplete_hours: {
    singular: "Prezlaber short on hours yesterday",
    plural: "Prezlabers short on hours yesterday",
  },
  late: {
    singular: "late Prezlaber today",
    plural: "late Prezlabers today",
  },
  review: { singular: "Prezlaber to review", plural: "Prezlabers to review" },
};

const PAGE_SIZE = 6;

export function ExceptionsPanel({ date }: { date?: string }) {
  const [filter, setFilter] = useState<FilterType>("all");
  const [expanded, setExpanded] = useState(false);
  const { data, isLoading } = useExceptions(date);
  const allItems = data?.items ?? [];
  const items = filter === "all" ? allItems : allItems.filter((i) => i.tag === filter);
  const visible = expanded ? items : items.slice(0, PAGE_SIZE);

  const subtitleCopy = SUBTITLE[filter];
  const subtitle = `${items.length} ${
    items.length === 1 ? subtitleCopy.singular : subtitleCopy.plural
  }`;

  return (
    <Panel>
      <PanelHeader
        title="Exceptions"
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

      {isLoading && (
        <div className="p-[18px] text-[12px] text-text-tertiary">Loading…</div>
      )}
      {!isLoading && items.length === 0 && (
        <div className="p-[18px] text-[12px] text-text-tertiary">
          Nothing to flag right now.
        </div>
      )}

      {visible.map((item) => (
        <ExceptionRow key={`${item.tag}:${item.emp_code}`} item={item} />
      ))}

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

function ExceptionRow({ item }: { item: ExceptionItem }) {
  const dotColor =
    item.severity === "high"
      ? "bg-severity-high"
      : item.severity === "medium"
        ? "bg-severity-med"
        : "bg-severity-low";

  return (
    <div className="flex cursor-pointer items-center gap-[14px] border-b border-border px-[18px] py-[14px] transition-colors hover:bg-bg-subtle">
      <div className={`h-[6px] w-[6px] shrink-0 rounded-full ${dotColor}`} />
      <div className="min-w-0 flex-1">
        <p className="m-0 text-[13px] font-medium">
          {item.name}{" "}
          <span className="font-normal text-text-secondary">
            · {item.department}
          </span>
        </p>
        <p className="m-0 mt-[2px] text-[12px] text-text-secondary">
          {item.detail}
        </p>
      </div>
      <Tag tag={item.tag} />
    </div>
  );
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
