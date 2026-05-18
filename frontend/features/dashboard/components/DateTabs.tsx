"use client";

// Daily, Weekly, and Monthly all wired to the dashboard mode.
const TABS = ["Daily", "Weekly", "Monthly"] as const;
type Tab = (typeof TABS)[number];

export function DateTabs({
  value,
  onChange,
}: {
  value: Tab;
  onChange: (v: Tab) => void;
}) {
  return (
    <div className="flex gap-1 rounded-md border border-border bg-bg-surface p-1">
      {TABS.map((t) => (
        <button
          key={t}
          type="button"
          onClick={() => onChange(t)}
          className={`rounded px-[14px] py-[6px] text-[13px] ${
            value === t
              ? "bg-bg-muted font-medium text-text-primary"
              : "text-text-secondary"
          }`}
        >
          {t}
        </button>
      ))}
    </div>
  );
}
