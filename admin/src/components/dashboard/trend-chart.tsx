"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Point = { date: string; conversations: number; leads: number };

/** Two count series on ONE axis (same unit), fixed categorical slots 1–2, 2px lines, legend +
 * crosshair tooltip (dataviz rules). Colours come from CSS vars → light/dark steps. */
export function TrendChart({
  data,
  labels,
}: {
  data: Point[];
  labels: { conversations: string; leads: string };
}) {
  const short = (d: string) => d.slice(5).replace("-", "/");
  return (
    <div className="h-64 w-full" role="img" aria-label={`${labels.conversations}, ${labels.leads}`}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: -16 }}>
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis
            dataKey="date"
            tickFormatter={short}
            tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            minTickGap={24}
          />
          <YAxis
            allowDecimals={false}
            tick={{ fill: "var(--muted-foreground)", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            cursor={{ stroke: "var(--muted-foreground)", strokeDasharray: "3 3" }}
            contentStyle={{
              background: "var(--popover)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              color: "var(--popover-foreground)",
              fontSize: 12,
            }}
            labelFormatter={(d) => String(d)}
          />
          <Legend
            iconType="plainline"
            wrapperStyle={{ fontSize: 12, color: "var(--muted-foreground)" }}
          />
          <Line
            type="monotone"
            dataKey="conversations"
            name={labels.conversations}
            stroke="var(--chart-1)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, stroke: "var(--chart-surface)", strokeWidth: 2 }}
          />
          <Line
            type="monotone"
            dataKey="leads"
            name={labels.leads}
            stroke="var(--chart-2)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, stroke: "var(--chart-surface)", strokeWidth: 2 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
