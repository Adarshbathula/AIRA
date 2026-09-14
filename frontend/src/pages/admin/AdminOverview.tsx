import { useEffect, useMemo, useState } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { dashboardApi, apiError } from "../../services/api";
import type { AuditEntry, ConfidenceDist, DocumentsStats, IncidentDashboard, RetrievalStats, RootCauseStats, SystemStats, UsageStats } from "../../types";
import ConfidenceBucketChart from "../../charts/ConfidenceBucketChart";
import CausePieChart from "../../charts/CausePieChart";
import { Badge, Card, EmptyState, ErrorNote, Kpi, Spinner } from "../../components/ui";
import { CATEGORY_COLORS, fmtDate, pct, qualityTone, relTime, severityTone } from "../../utils/format";

export default function AdminOverview() {
  const [system, setSystem] = useState<SystemStats | null>(null);
  const [ret, setRet] = useState<RetrievalStats | null>(null);
  const [conf, setConf] = useState<ConfidenceDist | null>(null);
  const [causes, setCauses] = useState<RootCauseStats | null>(null);
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [docs, setDocs] = useState<DocumentsStats | null>(null);
  const [inc, setInc] = useState<IncidentDashboard | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        const [a, b, c, d, e, f, g, h] = await Promise.all([
          dashboardApi.system(), dashboardApi.retrieval(), dashboardApi.confidence(), dashboardApi.rootCauses(),
          dashboardApi.usage(), dashboardApi.documents(), dashboardApi.incidents(30), dashboardApi.audit(30),
        ]);
        setSystem(a); setRet(b); setConf(c); setCauses(d); setUsage(e); setDocs(f); setInc(g); setAudit(h);
      } catch (e2) {
        setError(apiError(e2, "Admin analytics unavailable"));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const trend = useMemo(() => (inc?.trends.series ?? []).map((s) => ({ ...s, label: s.date.slice(5), conf: +(s.avg_confidence * 100).toFixed(0) })), [inc]);
  const typeChart = useMemo(() => (docs?.by_type ?? []).map((t) => ({ ...t, type: t.type.toUpperCase() })), [docs]);

  if (loading) return <div className="flex justify-center py-24 text-slate-400"><Spinner className="h-8 w-8" /></div>;
  if (error) return <ErrorNote message={error} />;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">Administration overview</h2>
        <p className="text-sm text-slate-500">System-wide incident, retrieval, knowledge-base and audit analytics.</p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Kpi label="Total incidents" value={system?.total_incidents ?? 0} hint={`${system?.resolved ?? 0} resolved`} />
        <Kpi label="High severity" value={system?.high_severity ?? 0} tone={(system?.high_severity ?? 0) > 0 ? "text-rose-600" : ""} hint="P0 / P1 across org" />
        <Kpi label="Knowledge documents" value={system?.documents ?? 0} hint={`${docs?.total_chunks ?? 0} chunks embedded`} />
        <Kpi label="Good retrieval" value={pct((ret?.good_pct ?? 0) / 100)} tone={(ret?.good_pct ?? 0) >= 70 ? "text-emerald-600" : "text-amber-600"}
          hint={`avg ${ret?.avg_retrieval_attempts ?? 0} attempts · avg conf ${pct(ret?.avg_confidence ?? 0)}`} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Most common root causes" subtitle="classified across assistant-analysed incidents" className="xl:col-span-2">
          {causes && <CausePieChart data={causes} />}
        </Card>
        <Card title="AI confidence distribution" subtitle={conf ? `${conf.total} incidents · avg ${pct(conf.avg)}` : ""}>
          {conf && conf.total > 0 ? <ConfidenceBucketChart data={conf} /> : <EmptyState title="No confidence data yet" />}
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Incident volume & confidence (30 days)" className="xl:col-span-2">
          {trend.some((t) => t.incidents) ? (
            <div className="h-52">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={trend} margin={{ left: -18, right: 8, top: 6 }}>
                  <defs>
                    <linearGradient id="gA" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#8b5cf6" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#8b5cf6" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke="#eef2f7" vertical={false} />
                  <XAxis dataKey="label" tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: "#64748b" }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
                  <Area type="monotone" dataKey="incidents" stroke="#7c3aed" fill="url(#gA)" strokeWidth={2} />
                  <Area type="monotone" dataKey="conf" stroke="#10b981" fill="none" strokeWidth={1.5} name="avg confidence %" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : <EmptyState title="No incidents in the last 30 days" />}
        </Card>

        <Card title="Retrieval statistics" subtitle={ret ? `${ret.total} assistant runs` : ""}>
          {ret && ret.total > 0 ? (
            <dl className="space-y-2 text-sm">
              <Stat k="Avg retrieval attempts" v={String(ret.avg_retrieval_attempts)} />
              <Stat k="GOOD context ratio" v={pct(ret.good_pct / 100)} tone="text-emerald-600" />
              <Stat k="POOR context ratio" v={pct(ret.poor_pct / 100)} tone="text-rose-600" />
              <Stat k="Avg supporting documents" v={String(ret.avg_supporting_documents)} />
              <Stat k="Avg AI confidence" v={pct(ret.avg_confidence)} />
            </dl>
          ) : <EmptyState title="No retrieval telemetry yet" />}
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Knowledge base usage" subtitle="documents most often cited by the assistant" className="xl:col-span-2" bodyClass="p-0">
          {usage && usage.most_referenced.length ? (
            <table className="w-full">
              <thead className="border-b border-slate-100 bg-slate-50/70">
                <tr><th className="th">Document</th><th className="th">Category</th><th className="th">Service</th><th className="th">References</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {usage.most_referenced.map((u) => (
                  <tr key={u.document_no}>
                    <td className="td font-medium text-slate-700">{u.name}</td>
                    <td className="td"><Badge tone="bg-violet-50 text-violet-700 ring-1 ring-violet-200">{u.category}</Badge></td>
                    <td className="td text-slate-600">{u.service ?? "—"}</td>
                    <td className="td tabular-nums font-semibold text-brand-600">{u.references}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <div className="p-5"><EmptyState title="No citations tracked yet" hint="Usage stats build up as incidents are analysed." /></div>}
        </Card>

        <Card title="Ingested formats" subtitle="by file type">
          {typeChart.length ? (
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={typeChart} margin={{ left: -22, right: 8 }}>
                  <CartesianGrid stroke="#eef2f7" vertical={false} />
                  <XAxis dataKey="type" tick={{ fontSize: 10, fill: "#64748b" }} axisLine={false} tickLine={false} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: "#64748b" }} axisLine={false} tickLine={false} />
                  <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} cursor={{ fill: "#f1f5f9" }} />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {typeChart.map((_, i) => <Cell key={i} fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <EmptyState title="No documents yet" />}
        </Card>
      </div>

      <Card title="Audit trail" subtitle="security-relevant actions (uploads, deletions, auth, role changes)" bodyClass="p-0">
        {audit.length ? (
          <ul className="divide-y divide-slate-100">
            {audit.slice(0, 12).map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2 px-4 py-2 text-xs">
                <span className="font-mono font-semibold text-slate-700">{a.action}</span>
                {a.entity_type && <Badge>{a.entity_type} {a.entity_id}</Badge>}
                <span className="text-slate-500">user #{a.user_id ?? "?"}</span>
                {a.detail && <span className="truncate font-mono text-[10px] text-slate-400">{JSON.stringify(a.detail).slice(0, 90)}</span>}
                <span className="ml-auto whitespace-nowrap text-slate-400">{relTime(a.created_at)} · {fmtDate(a.created_at)}</span>
              </li>
            ))}
          </ul>
        ) : <div className="p-5"><EmptyState title="No audit entries yet" /></div>}
      </Card>

      {inc && inc.recent.length > 0 && (
        <Card title="Latest incidents (org-wide)" bodyClass="p-0">
          <table className="w-full">
            <thead className="border-b border-slate-100 bg-slate-50/70">
              <tr><th className="th">Incident</th><th className="th">Service</th><th className="th">Sev</th><th className="th">Confidence</th><th className="th">Retrieval</th><th className="th">Status</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {inc.recent.slice(0, 6).map((r) => (
                <tr key={r.id}>
                  <td className="td max-w-[40ch]"><p className="truncate text-slate-700">{r.description}</p><span className="font-mono text-[10px] text-slate-400">{r.public_id}</span></td>
                  <td className="td text-slate-600">{r.service ?? "—"}</td>
                  <td className="td"><Badge tone={severityTone(r.severity)}>{r.severity ?? "—"}</Badge></td>
                  <td className="td tabular-nums">{pct(r.confidence_score)}</td>
                  <td className="td"><Badge tone={qualityTone(r.retrieval_quality)}>{r.retrieval_quality}</Badge></td>
                  <td className="td text-xs text-slate-500">{r.resolution_status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function Stat({ k, v, tone = "text-slate-800" }: { k: string; v: string; tone?: string }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2">
      <dt className="text-xs text-slate-500">{k}</dt>
      <dd className={`text-sm font-semibold tabular-nums ${tone}`}>{v}</dd>
    </div>
  );
}
