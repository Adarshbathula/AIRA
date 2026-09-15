import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ConfidenceDist } from "../types";

const COLORS = ["#059669", "#10b981", "#f59e0b", "#60a5fa", "#e11d48"];

export default function ConfidenceBucketChart({ data }: { data: ConfidenceDist }) {
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data.buckets} margin={{ left: -22, right: 8, top: 6 }}>
          <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
          <XAxis dataKey="bucket" tick={{ fontSize: 11, fill: "var(--chart-axis)" }} axisLine={false} tickLine={false} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "var(--chart-axis)" }} axisLine={false} tickLine={false} />
          <Tooltip cursor={{ fill: "var(--chart-cursor)" }} />
          <Bar dataKey="count" radius={[4, 4, 0, 0]} name="incidents">
            {data.buckets.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
