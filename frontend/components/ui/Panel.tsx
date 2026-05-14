import type { ReactNode } from "react";

export function Panel({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-bg-surface">
      {children}
    </div>
  );
}

export function PanelHeader({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between border-b border-border px-[18px] py-[14px]">
      <div>
        <h3 className="m-0 text-[14px] font-medium">{title}</h3>
        {subtitle && (
          <p className="mt-[2px] text-[12px] text-text-tertiary">{subtitle}</p>
        )}
      </div>
      {right}
    </div>
  );
}

export function SidePanel({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col rounded-lg border border-border bg-bg-surface px-[18px] py-4">
      <p className="m-0 mb-3 text-[12px] font-medium uppercase tracking-[0.04em] text-text-secondary">
        {label}
      </p>
      {children}
    </div>
  );
}
