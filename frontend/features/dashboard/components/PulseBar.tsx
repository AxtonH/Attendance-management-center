"use client";

import { Tile, TileLabel, TileValue } from "@/components/ui/Tile";

import { useOverview, type DashboardMode } from "../queries";

export function PulseBar({
  date,
  mode = "daily",
}: {
  date?: string;
  mode?: DashboardMode;
}) {
  const { data, isLoading, isError } = useOverview(date, mode);
  // In range modes the numbers are sums (or distinct people for Present);
  // suffix makes that explicit so 14 Late doesn't read as 14 lates today.
  const suffix =
    mode === "weekly" ? " this week" : mode === "monthly" ? " this month" : "";

  return (
    <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Tile>
        <TileLabel>Present{suffix}</TileLabel>
        <TileValue>{renderNumber(data?.present, isLoading, isError)}</TileValue>
      </Tile>
      <Tile>
        <TileLabel>Late{suffix}</TileLabel>
        <TileValue tone="warning">
          {renderNumber(data?.late, isLoading, isError)}
        </TileValue>
      </Tile>
      <Tile>
        <TileLabel>Absent{suffix}</TileLabel>
        <TileValue tone="danger">
          {renderNumber(data?.absent ?? undefined, isLoading, isError)}
        </TileValue>
      </Tile>
    </div>
  );
}

function renderNumber(
  value: number | undefined,
  loading: boolean,
  error: boolean,
): string | number {
  if (error) return "—";
  if (loading || value === undefined) return "…";
  return value;
}
