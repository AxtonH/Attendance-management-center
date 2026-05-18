"use client";

import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
} from "recharts";
import type { TooltipContentProps } from "recharts";

import { SidePanel } from "@/components/ui/Panel";

import { useArrivals, type DashboardMode } from "../queries";

const ACCENT = "#4F46E5"; // matches --accent token

export function ArrivalHistogram({
  date,
  mode = "daily",
}: {
  date?: string;
  mode?: DashboardMode;
}) {
  const { data } = useArrivals(date, mode);
  const buckets = data?.buckets ?? [];

  return (
    <SidePanel
      label={
        mode === "daily"
          ? "Today's arrival pattern"
          : "Average arrival pattern"
      }
    >
      {/* flex-1 grows the chart to fill whatever vertical space the
          grid hands the panel — keeps it the same height as the
          department rollup next door. min-h-0 is the standard fix that
          lets a flex child shrink rather than overflowing. */}
      <div className="min-h-0 w-full flex-1">
        {buckets.length === 0 ? (
          <p className="text-[12px] text-text-tertiary">No arrivals recorded yet.</p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={buckets}
              // No YAxis → use Recharts' standard left margin of 0.
              // Earlier negative-left pulled the cursor zone off-canvas,
              // which is what was killing the hover tooltip.
              margin={{ top: 8, right: 4, left: 0, bottom: 4 }}
            >
              <defs>
                <linearGradient id="arrivalFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={ACCENT} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={ACCENT} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis
                dataKey="label"
                tick={{ fontSize: 10, fill: "#8C8C90" }}
                tickLine={false}
                axisLine={false}
                interval="preserveStartEnd"
                tickMargin={6}
              />
              {/* No <YAxis />: arrivals is a shape, not a precise count.
                  Tooltip surfaces the exact number on hover. */}
              <Tooltip
                cursor={{ stroke: "#E5E5E4", strokeWidth: 1 }}
                content={<ArrivalTooltip />}
              />
              <Area
                type="monotone"
                dataKey="count"
                stroke={ACCENT}
                strokeWidth={2}
                fill="url(#arrivalFill)"
                // baseValue=0 anchors the fill to the bottom even when
                // every bucket is zero — no more floating curve.
                baseValue={0}
              />
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </SidePanel>
  );
}

type ArrivalTooltipProps = Partial<TooltipContentProps<number, string>>;

function ArrivalTooltip({ active, payload, label }: ArrivalTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const count = payload[0].value;
  return (
    <div className="rounded-md border border-border bg-bg-surface px-[10px] py-[6px] text-[12px] shadow-sm">
      <div className="text-text-secondary">{label}</div>
      <div className="font-medium text-text-primary">
        {count} {count === 1 ? "arrival" : "arrivals"}
      </div>
    </div>
  );
}
