import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { RootCauseStats } from "../types";
import { CATEGORY_COLORS } from "../utils/format";

export default function CausePieChart({ data }: { data: RootCauseStats }) {
  const rows = data.distribution.map((d) => ({ ...d, label: `${d.label} (${d.pct}%)` }));
  if (!rows.length) {
    return <p className="py-10 text-center text-sm text-slate-400 dark:text-slate-500">No classified root causes yet.</p>;
  }
  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="h-52 w-52 shrink-0">
        <ResponsiveContainer width="100%" height="100%">
          <PieChart>
            <Pie data={rows} dataKey="count" nameKey="label" innerRadius={44} outerRadius={78} paddingAngle={2} stroke="var(--surface-card)">
              {rows.map((_, i) => <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />)}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="min-w-0 flex-1 space-y-1">
        {rows.map((d, i) => (
          <li key={d.label} className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300">
            <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: CATEGORY_COLORS[i % CATEGORY_COLORS.length] }} />
            <span className="truncate">{d.label.replace(/\s\([\d.]+%\)$/, "")}</span>
            <span className="ml-auto shrink-0 font-medium tabular-nums text-slate-500 dark:text-slate-400">{d.pct}%</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
