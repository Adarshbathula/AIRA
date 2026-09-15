import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { incidentApi, apiError } from "../services/api";
import { useAuth } from "../context/AuthContext";
import type { IncidentSummary } from "../types";
import { Badge, Card, EmptyState, ErrorNote, Spinner } from "../components/ui";
import { fmtDate, pct, qualityTone, severityTone } from "../utils/format";
import { useToast } from "../hooks/useToast";

export default function Incidents() {
  const { isAdmin } = useAuth();
  const [rows, setRows] = useState<IncidentSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [severity, setSeverity] = useState("");
  const [quality, setQuality] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const toast = useToast();
  const limit = 15;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await incidentApi.list({
        limit, offset: page * limit,
        search: search || undefined, severity: severity || undefined,
        quality: quality || undefined, status: statusFilter || undefined,
      });
      setRows(res.items); setTotal(res.total);
    } catch (e) {
      setError(apiError(e, "Could not load incidents"));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page, search, severity, quality, statusFilter]);

  useEffect(() => { void load(); }, [load]);

  const resolve = async (row: IncidentSummary) => {
    setBusyId(row.id);
    try {
      await incidentApi.resolve(row.id, row.resolution_status === "RESOLVED" ? "OPEN" : "RESOLVED");
      toast.success(row.resolution_status === "RESOLVED" ? "Re-opened" : "Marked resolved — added to historical match set");
      void load();
    } catch (e) {
      toast.error(apiError(e));
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (row: IncidentSummary) => {
    if (!window.confirm(`Delete incident ${row.public_id}? This removes its conversation record and evidence links.`)) return;
    try {
      await incidentApi.remove(row.id);
      toast.success("Incident deleted");
      void load();
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Incident register</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            {isAdmin ? "All analyses across the organisation" : "Your analysed incidents"} · historical records are also used for similar-incident matching.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input className="input w-56" placeholder="Search text / service / id…" value={search} onChange={(e) => { setSearch(e.target.value); setPage(0); }} />
          <select className="input w-32" value={severity} onChange={(e) => { setSeverity(e.target.value); setPage(0); }}>
            <option value="">Any severity</option>
            {["P0", "P1", "P2", "P3", "P4"].map((s) => <option key={s}>{s}</option>)}
          </select>
          <select className="input w-36" value={quality} onChange={(e) => { setQuality(e.target.value); setPage(0); }}>
            <option value="">Any retrieval</option>
            <option>GOOD</option><option>FAIR</option><option>POOR</option>
          </select>
          <select className="input w-36" value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(0); }}>
            <option value="">Any status</option>
            <option>OPEN</option><option>MITIGATED</option><option>RESOLVED</option>
          </select>
        </div>
      </div>

      {error && <ErrorNote message={error} />}

      <Card bodyClass="p-0">
        {loading ? (
          <div className="flex justify-center py-20 text-slate-400 dark:text-slate-500"><Spinner className="h-7 w-7" /></div>
        ) : rows.length === 0 ? (
          <div className="p-6"><EmptyState title="No incidents match" hint="Adjust the filters, or analyse a new incident." /></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px]">
              <thead className="border-b border-slate-100 dark:border-white/5 bg-slate-50/70">
                <tr>
                  <th className="th">Incident</th><th className="th">Service</th><th className="th">Category</th>
                  <th className="th">Severity</th><th className="th">Confidence</th><th className="th">Retrieval</th>
                  <th className="th">Status</th><th className="th">Created</th><th className="th text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                {rows.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50/70 hover:dark:bg-white/5">
                    <td className="td max-w-[34ch]">
                      <Link to={`/incidents/${r.id}`} className="block truncate font-medium text-slate-800 dark:text-slate-200 hover:text-brand-600">{r.description}</Link>
                      <span className="font-mono text-[10px] text-slate-400 dark:text-slate-500">{r.public_id}</span>
                    </td>
                    <td className="td text-slate-600 dark:text-slate-300">{r.service ?? "—"}</td>
                    <td className="td text-xs text-slate-500 dark:text-slate-400">{r.category ?? "—"}</td>
                    <td className="td"><Badge tone={severityTone(r.severity)}>{r.severity ?? "—"}</Badge></td>
                    <td className="td tabular-nums">
                      <span className={r.confidence_score >= 0.7 ? "font-semibold text-emerald-700 dark:text-emerald-300" : r.confidence_score >= 0.45 ? "text-amber-700" : "text-rose-600"}>
                        {pct(r.confidence_score)}
                      </span>
                    </td>
                    <td className="td">
                      <Badge tone={qualityTone(r.retrieval_quality)}>{r.retrieval_quality}</Badge>
                      {r.retrieval_attempts > 1 && <span className="ml-1 text-[10px] text-slate-400 dark:text-slate-500">×{r.retrieval_attempts} healed</span>}
                    </td>
                    <td className="td">
                      <Badge tone={r.resolution_status === "RESOLVED" ? "bg-emerald-100 text-emerald-700 dark:text-emerald-300 ring-1 ring-emerald-200" : "bg-slate-100 dark:bg-[#212121] text-slate-600 dark:text-slate-300 ring-1 ring-slate-200 dark:ring-white/10"}>
                        {r.resolution_status}
                      </Badge>
                    </td>
                    <td className="td whitespace-nowrap text-xs text-slate-500 dark:text-slate-400">{fmtDate(r.created_at)}</td>
                    <td className="td text-right whitespace-nowrap">
                      <button className="text-xs font-medium text-brand-600 dark:text-brand-400 hover:underline" onClick={() => void resolve(r)} disabled={busyId === r.id}>
                        {busyId === r.id ? "…" : r.resolution_status === "RESOLVED" ? "re-open" : "resolve"}
                      </button>
                      <Link to={`/incidents/${r.id}`} className="ml-3 text-xs font-medium text-slate-500 dark:text-slate-400 hover:underline">details</Link>
                      {isAdmin && <button className="ml-3 text-xs font-medium text-rose-600 hover:underline" onClick={() => void remove(r)}>delete</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
        <span>{total} incident(s)</span>
        <div className="flex items-center gap-2">
          <button className="btn-ghost px-2.5 py-1" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>← Prev</button>
          <span>page {page + 1} / {Math.max(1, Math.ceil(total / limit))}</span>
          <button className="btn-ghost px-2.5 py-1" disabled={(page + 1) * limit >= total} onClick={() => setPage((p) => p + 1)}>Next →</button>
        </div>
      </div>
    </div>
  );
}
