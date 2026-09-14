import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { dashboardApi } from "../services/api";
import { apiError } from "../services/api";
import { useAuth } from "../context/AuthContext";
import type { DashboardOverview, IncidentDashboard, RetrievalStats } from "../types";
import { Badge, Card, EmptyState, ErrorNote, Spinner } from "../components/ui";
import { CATEGORY_COLORS, pct, qualityTone, relTime, severityTone } from "../utils/format";

export default function Dashboard() {
  const { user } = useAuth();
  const [ov, setOv] = useState<DashboardOverview | null>(null);
  const [inc, setInc] = useState<IncidentDashboard | null>(null);
  const [ret, setRet] = useState<RetrievalStats | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    void (async () => {
      try {
        const [a, b, c] = await Promise.all([dashboardApi.overview(), dashboardApi.incidents(14), dashboardApi.retrieval()]);
        if (!alive) return;
        setOv(a); setInc(b); setRet(c);
      } catch (e) {
        if (alive) setError(apiError(e, "Could not load dashboard"));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => { alive = false; };
  }, []);

  const trendData = useMemo(
    () => (inc?.trends.series ?? []).map((d) => ({ ...d, label: d.date.slice(5), conf: +(d.avg_confidence * 100).toFixed(0) })),
    [inc],
  );
  const serviceData = useMemo(() => (inc?.top_services ?? []).slice(0, 6), [inc]);

  if (loading) return <div className="flex justify-center py-24 text-slate-400"><Spinner className="h-8 w-8" /></div>;
  if (error) return <ErrorNote message={error} />;
  if (!ov) return <EmptyState title="No dashboard data yet" hint="Analyse your first incident in the assistant." />;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Welcome back, {user?.name?.split(" ")[0]}</h2>
          <p className="text-sm text-slate-500">Operational snapshot across analysed incidents{user?.role === "admin" ? " (org-wide)" : " (your workspace)"}.</p>
        </div>
        <Link to="/assistant" className="btn-primary">+ New Incident Analysis</Link>
      </div>

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-5">
        <Kpi label="Incidents analysed" value={ov.total_incidents} hint={`${ov.incidents_last_7_days} in the last 7 days`} />
        <Kpi label="Avg AI confidence" value={pct(ov.avg_confidence)} hint="across your analysed incidents" tone={ov.avg_confidence >= 0.7 ? "text-emerald-600" : "text-amber-600"} />
        <Kpi label="Good retrieval" value={pct(ov.good_retrieval_pct)} hint={`avg ${ov.avg_retrieval_attempts} retrieval attempt(s)`} />
        <Kpi label="High severity (P0/P1)" value={ov.high_severity} hint={`${ov.resolved_incidents} marked resolved`} tone={ov.high_severity ? "text-rose-600" : "text-slate-900"} />
        <Kpi label="Knowledge base" value={ov.documents} hint={`${ov.document_chunks} indexed chunks`} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Incidents & confidence trend" subtitle="last 14 days" className="xl:col-span-2">
          {trendData.some((d) => d.incidents > 0) ? (
            <div className="h-56">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trendData} margin={{ left: -18, right: 8, top: 6 }}>
                  <defs>
                    <linearGradient id="g1" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#2b5ac4" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#2b5ac4" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#eef2f7" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  <Area type="monotone" dataKey="incidents" stroke="#2b5ac4" fill="url(#g1)" strokeWidth={2} name="incidents" />
                  <Area type="monotone" dataKey="conf" stroke="#10b981" fill="none" strokeWidth={1.6} name="avg confidence %" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : <EmptyState title="No incidents in the last 14 days" hint="Run an analysis from the assistant to populate this chart." />}
        </Card>

        <Card title="Retrieval health" subtitle={ret ? `${ret.total} assistant runs` : ""}>
          {ret && ret.total > 0 ? (
            <div className="space-y-3 text-sm">
              <StatRow label="Avg attempts" value={String(ret.avg_retrieval_attempts)} />
              <StatRow label="Avg supporting docs" value={String(ret.avg_supporting_documents)} />
              <StatRow label="Avg similarity" value={pct(ret.avg_confidence)} />
              <div className="rounded-lg bg-slate-50 p-3">
                <div className="mb-1 flex justify-between text-xs text-slate-500">
                  <span>GOOD {pct(ret.good_pct / 100)}</span>
                  <span>POOR {pct(ret.poor_pct / 100)}</span>
                </div>
                <div className="flex h-2 overflow-hidden rounded-full bg-slate-200">
                  <div className="bg-emerald-500" style={{ width: `${ret.good_pct}%` }} />
                  <div className="bg-amber-400" style={{ width: `${Math.max(0, 100 - ret.good_pct - ret.poor_pct)}%` }} />
                  <div className="bg-rose-500" style={{ width: `${ret.poor_pct}%` }} />
                </div>
              </div>
            </div>
          ) : <EmptyState title="No retrieval telemetry yet" />}
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Recent incidents" className="xl:col-span-2" bodyClass="p-0">
          {inc && inc.recent.length ? (
            <table className="w-full">
              <thead className="border-b border-slate-100 bg-slate-50/70">
                <tr>
                  <th className="th">Incident</th><th className="th">Service</th><th className="th">Sev</th>
                  <th className="th">Confidence</th><th className="th">Retrieval</th><th className="th">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {inc.recent.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50">
                    <td className="td max-w-[36ch]">
                      <Link to={`/incidents/${r.id}`} className="block truncate font-medium text-slate-800 hover:text-brand-600">
                        {r.description}
                      </Link>
                      <span className="font-mono text-[10px] text-slate-400">{r.public_id}</span>
                    </td>
                    <td className="td text-slate-600">{r.service ?? "—"}</td>
                    <td className="td"><Badge tone={severityTone(r.severity)}>{r.severity ?? "—"}</Badge></td>
                    <td className="td tabular-nums">{pct(r.confidence_score)}</td>
                    <td className="td"><Badge tone={qualityTone(r.retrieval_quality)}>{r.retrieval_quality}</Badge></td>
                    <td className="td whitespace-nowrap text-xs text-slate-500">{relTime(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-5"><EmptyState title="No incidents analysed yet" hint="Describe a production incident in the assistant." /></div>
          )}
        </Card>

        <Card title="Frequently affected services" subtitle="incident count by service">
          {serviceData.length ? (
            <div className="h-52">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={serviceData} layout="vertical" margin={{ left: 8, right: 16, top: 4, bottom: 4 }}>
                  <CartesianGrid stroke="#eef2f7" horizontal={false} />
                  <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="service" width={120} tick={{ fontSize: 11, fill: "#334155" }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  <Bar dataKey="count" radius={[0, 4, 4, 0]} name="incidents">
                    {serviceData.map((_, i) => <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <EmptyState title="No service data yet" />}
        </Card>
      </div>
    </div>
  );
}

function Kpi({ label, value, hint, tone }: { label: string; value: React.ReactNode; hint?: string; tone?: string }) {
  return (
    <div className="card p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${tone ?? "text-slate-900"}`}>{value}</p>
      {hint && <p className="mt-0.5 text-[11px] text-slate-500">{hint}</p>}
    </div>
  );
}

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-sm font-semibold tabular-nums text-slate-800">{value}</span>
    </div>
  );
}
