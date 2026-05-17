"use client";

// Daily and Weekly are wired to the dashboard mode. Monthly is reserved
// for a future phase — clicks are intercepted to keep it inert without
// removing the visual.
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
      {TABS.map((t) => {
        const disabled = t === "Monthly";
        return (
          <button
            key={t}
            type="button"
            disabled={disabled}
            onClick={() => !disabled && onChange(t)}
            title={disabled ? "Coming soon" : undefined}
            className={`rounded px-[14px] py-[6px] text-[13px] ${
              value === t
                ? "bg-bg-muted font-medium text-text-primary"
                : disabled
                  ? "cursor-not-allowed text-text-tertiary"
                  : "text-text-secondary"
            }`}
          >
            {t}
          </button>
        );
      })}
    </div>
  );
}
