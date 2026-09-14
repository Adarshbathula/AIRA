import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { ConfidenceDist } from "../types";

const COLORS = ["#059669", "#10b981", "#f59e0b", "#60a5fa", "#e11d48"];

export default function ConfidenceBucketChart({ data }: { data: ConfidenceDist }) {
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data.buckets} margin={{ left: -22, right: 8, top: 6 }}>
          <CartesianGrid stroke="#eef2f7" vertical={false} />
          <XAxis dataKey="bucket" tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} />
          <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} />
          <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} cursor={{ fill: "#f1f5f9" }} />
          <Bar dataKey="count" radius={[4, 4, 0, 0]} name="incidents">
            {data.buckets.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
