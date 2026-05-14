"use client";

import { Tile, TileLabel, TileValue } from "@/components/ui/Tile";

import { useOverview } from "../queries";

export function PulseBar({ date }: { date?: string }) {
  const { data, isLoading, isError } = useOverview(date);

  return (
    <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Tile>
        <TileLabel>Present</TileLabel>
        <TileValue>{renderNumber(data?.present, isLoading, isError)}</TileValue>
      </Tile>
      <Tile>
        <TileLabel>Late</TileLabel>
        <TileValue tone="warning">
          {renderNumber(data?.late, isLoading, isError)}
        </TileValue>
      </Tile>
      <Tile>
        <TileLabel>Absent</TileLabel>
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
