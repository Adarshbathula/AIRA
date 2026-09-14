import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { chatApi, apiError } from "../services/api";
import type { Conversation } from "../types";
import { Badge, Card, EmptyState, ErrorNote, Modal, Spinner } from "../components/ui";
import { fmtDate, pct, qualityTone, relTime } from "../utils/format";
import { useToast } from "../hooks/useToast";

export default function History() {
  const [rows, setRows] = useState<Conversation[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [renameId, setRenameId] = useState<number | null>(null);
  const [renameText, setRenameText] = useState("");
  const [deleting, setDeleting] = useState<number | null>(null);
  const navigate = useNavigate();
  const toast = useToast();

  const load = useMemo(() => async () => {
    setLoading(true);
    try { setRows(await chatApi.list(search || undefined)); }
    catch (e) { setError(apiError(e, "Could not load conversations")); }
    finally { setLoading(false); }
  }, [search]);

  useEffect(() => {
    const t = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(t);
  }, [load]);

  const doDelete = async (id: number) => {
    setDeleting(id);
    try {
      await chatApi.remove(id);
      toast.success("Conversation deleted");
      setRows((r) => r.filter((x) => x.id !== id));
    } catch (e) {
      toast.error(apiError(e, "Delete failed"));
    } finally {
      setDeleting(null);
    }
  };

  const doRename = async () => {
    if (renameId == null || !renameText.trim()) return;
    try {
      await chatApi.rename(renameId, renameText.trim());
      toast.success("Conversation renamed");
      setRenameId(null);
      void load();
    } catch (e) {
      toast.error(apiError(e, "Rename failed"));
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Conversation history</h2>
          <p className="text-sm text-slate-500">Every incident analysis is preserved with its evidence trail — click to resume in the assistant.</p>
        </div>
        <input className="input w-72" placeholder="Search titles & message text…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      {error && <ErrorNote message={error} />}

      {loading ? (
        <div className="flex justify-center py-20 text-slate-400"><Spinner className="h-7 w-7" /></div>
      ) : rows.length === 0 ? (
        <EmptyState title="No conversations yet" hint="Run your first incident analysis from the Incident Assistant." />
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {rows.map((c) => (
            <Card key={c.id} className="flex flex-col justify-between">
              <div>
                <div className="flex items-start justify-between gap-2">
                  <button className="text-left text-sm font-semibold text-slate-800 hover:text-brand-600" onClick={() => navigate(`/assistant?c=${c.id}`)}>
                    {c.title}
                  </button>
                  <Badge tone={qualityTone(c.last_incident?.retrieval_quality)}>{c.last_incident?.retrieval_quality ?? "—"}</Badge>
                </div>
                {c.last_incident?.probable_root_cause && (
                  <p className="mt-1.5 line-clamp-2 text-xs text-slate-500">{c.last_incident.probable_root_cause}</p>
                )}
                <p className="mt-2 text-[11px] text-slate-400">
                  {c.message_count} messages · {c.incident_count} incident{c.incident_count === 1 ? "" : "s"} · updated {relTime(c.updated_at)}
                </p>
              </div>
              <div className="mt-3 flex items-center justify-between border-t border-slate-100 pt-2.5 text-[11px] text-slate-500">
                <span>conf. {pct(c.last_incident?.confidence_score)}</span>
                <span className="flex gap-2">
                  <button className="font-medium text-brand-600 hover:underline" onClick={() => { setRenameId(c.id); setRenameText(c.title); }}>Rename</button>
                  <button className="font-medium text-rose-600 hover:underline" onClick={() => void doDelete(c.id)} disabled={deleting === c.id}>
                    {deleting === c.id ? "Deleting…" : "Delete"}
                  </button>
                </span>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal open={renameId != null} onClose={() => setRenameId(null)} title="Rename conversation">
        <input className="input" value={renameText} onChange={(e) => setRenameText(e.target.value)} autoFocus onKeyDown={(e) => e.key === "Enter" && void doRename()} />
        <div className="mt-3 flex justify-end gap-2">
          <button className="btn-ghost" onClick={() => setRenameId(null)}>Cancel</button>
          <button className="btn-primary" onClick={() => void doRename()}>Save</button>
        </div>
      </Modal>
    </div>
  );
}
