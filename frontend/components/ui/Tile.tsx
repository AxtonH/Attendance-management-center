import type { ReactNode } from "react";

export function Tile({ children }: { children: ReactNode }) {
  return (
    <div className="cursor-pointer rounded-md border border-border bg-bg-surface px-[18px] py-4 transition-colors hover:border-border-strong">
      {children}
    </div>
  );
}

export function TileLabel({ children }: { children: ReactNode }) {
  return <p className="m-0 text-[12px] text-text-secondary">{children}</p>;
}

export function TileValue({
  children,
  tone = "default",
  sub,
}: {
  children: ReactNode;
  tone?: "default" | "warning" | "danger";
  sub?: ReactNode;
}) {
  const color =
    tone === "warning"
      ? "text-amber-700"
      : tone === "danger"
        ? "text-red-700"
        : "text-text-primary";
  return (
    <p className={`mt-[6px] text-[26px] font-medium leading-none ${color}`}>
      {children}
      {sub !== undefined && (
        <span className="ml-1 text-[13px] font-normal text-text-tertiary">
          {sub}
        </span>
      )}
    </p>
  );
}
