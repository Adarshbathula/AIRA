import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { incidentApi, apiError } from "../services/api";
import { useAuth } from "../context/AuthContext";
import type { AIResponse, SimilarIncident } from "../types";
import AssistantResponse from "../components/AssistantResponse";
import { Badge, Card, EmptyState, ErrorNote, Spinner } from "../components/ui";
import { fmtDate, pct } from "../utils/format";
import { useToast } from "../hooks/useToast";

export default function IncidentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [ai, setAi] = useState<AIResponse | null>(null);
  const [related, setRelated] = useState<SimilarIncident[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const detail = await incidentApi.detail(Number(id));
      setAi(detail);
      setStatus(detail.insufficient_evidence ? "OPEN" : "OPEN");
      incidentApi.similar({ incident_id: Number(id), top_k: 6 })
        .then((r) => setRelated(r.filter((x) => x.public_id !== detail.public_id)))
        .catch(() => undefined);
    } catch (e) {
      setError(apiError(e, "Incident not found"));
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { void load(); }, [load]);

  const changeStatus = async (s: string) => {
    if (!ai) return;
    try {
      await incidentApi.resolve(ai.incident_id, s);
      toast.success(`Marked ${s}`);
      void load();
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  const remove = async () => {
    if (!ai || !window.confirm("Delete this incident record?")) return;
    try {
      await incidentApi.remove(ai.incident_id);
      toast.success("Incident deleted");
      navigate("/incidents");
    } catch (e) {
      toast.error(apiError(e));
    }
  };

  if (loading) return <div className="flex justify-center py-24 text-slate-400"><Spinner className="h-8 w-8" /></div>;
  if (error || !ai) return <ErrorNote message={error || "Unknown error"} />;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Link to="/incidents" className="text-xs font-medium text-slate-500 hover:text-brand-600">← Incidents</Link>
        <h2 className="text-lg font-semibold text-slate-900">{ai.public_id}</h2>
        <span className="text-xs text-slate-500">{fmtDate(ai.timestamp)}</span>
        <div className="ml-auto flex items-center gap-2">
          <select className="input w-40 py-1.5 text-xs" value={status} onChange={(e) => void changeStatus(e.target.value)}>
            <option value="OPEN" disabled>Set status…</option>
            <option value="OPEN">OPEN</option>
            <option value="MITIGATED">MITIGATED</option>
            <option value="RESOLVED">RESOLVED</option>
          </select>
          {ai.conversation_id && (
            <button className="btn-ghost" onClick={() => navigate(`/assistant?c=${ai.conversation_id}`)}>Resume conversation</button>
          )}
          {isAdmin && <button className="btn-danger" onClick={() => void remove()}>Delete</button>}
        </div>
      </div>

      <Card bodyClass="p-0"><div className="p-4 sm:p-5"><AssistantResponse ai={ai} /></div></Card>

      <Card title="More historically similar incidents" subtitle="semantic similarity over description, service and known causes">
        {related.length ? (
          <ul className="grid gap-2 md:grid-cols-2">
            {related.map((s) => (
              <li key={s.public_id} className="rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-xs font-semibold text-slate-700">{s.public_id}</span>
                  {s.severity && <Badge tone="bg-slate-100 text-slate-600 ring-1 ring-slate-200">{s.severity}</Badge>}
                  <span className="ml-auto text-xs font-semibold text-emerald-700">{pct(s.similarity)}</span>
                </div>
                <p className="mt-1 text-xs text-slate-600">{s.title}</p>
                {s.root_cause && <p className="mt-0.5 text-[11px] text-slate-500">cause: {s.root_cause}</p>}
                {s.resolution && <p className="text-[11px] text-emerald-700">fix: {s.resolution}</p>}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No other similar incidents" hint="This pattern has not been seen before — document a postmortem after resolution." />
        )}
      </Card>
    </div>
  );
}
