import { useCallback, useEffect, useState } from "react";
import { documentApi, apiError } from "../../services/api";
import type { DocumentItem } from "../../types";
import { Badge, Card, EmptyState, ErrorNote, Modal, Spinner } from "../../components/ui";
import { fmtBytes, fmtDate } from "../../utils/format";
import { useToast } from "../../hooks/useToast";
import UploadDialog from "../../components/UploadDialog";

const CATEGORIES = ["SOP", "RUNBOOK", "JIRA_INCIDENT", "RCA", "INCIDENT_REPORT", "ARCHITECTURE",
  "DEPLOYMENT_GUIDE", "TROUBLESHOOTING_GUIDE", "KNOWLEDGE_BASE", "CHANGE_REQUEST", "POSTMORTEM", "LOG"];

export default function DocumentsAdmin() {
  const toast = useToast();
  const [rows, setRows] = useState<DocumentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [page, setPage] = useState(0);
  const [q, setQ] = useState("");
  const [cat, setCat] = useState("");
  const [svc, setSvc] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [editing, setEditing] = useState<DocumentItem | null>(null);
  const [form, setForm] = useState({ category: "", service: "", department: "", version: "", author: "" });
  const limit = 20;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await documentApi.list({ limit, offset: page * limit, search: q || undefined, category: cat || undefined, service: svc || undefined });
      setRows(res.items); setTotal(res.total);
    } catch (e) {
      setError(apiError(e, "Could not load documents"));
    } finally {
      setLoading(false);
    }
  }, [q, cat, svc, page]);

  useEffect(() => {
    const t = window.setTimeout(() => void load(), 220);
    return () => window.clearTimeout(t);
  }, [load]);

  const openEdit = async (d: DocumentItem) => {
    setEditing(d);
    setForm({ category: d.category, service: d.service ?? "", department: d.department ?? "", version: d.version ?? "", author: d.author ?? "" });
  };

  const saveEdit = async () => {
    if (!editing) return;
    try {
      const clean = Object.fromEntries(Object.entries(form).filter(([, v]) => v.trim().length > 0));
      await documentApi.update(editing.id, clean);
      toast.success("Metadata updated — retrieval indexes re-synced");
      setEditing(null);
      void load();
    } catch (e) {
      toast.error(apiError(e, "Update failed"));
    }
  };

  const remove = async (d: DocumentItem) => {
    if (!window.confirm(`Delete ${d.name}?\n\nAll chunks are removed from the FAISS index, so the assistant will no longer cite it.`)) return;
    try {
      await documentApi.remove(d.id);
      toast.success("Document removed from knowledge base");
      void load();
    } catch (e) {
      toast.error(apiError(e, "Delete failed"));
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">Document management</h2>
          <p className="text-sm text-slate-500 dark:text-slate-400">Ingest, categorise and retire the enterprise corpus that grounds every AI answer.</p>
        </div>
        <button className="btn-primary" onClick={() => setUploadOpen(true)}>⇪ Upload</button>
      </div>

      <div className="flex flex-wrap gap-2">
        <input className="input w-72" placeholder="Search name / number / service…" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} />
        <select className="input w-48" value={cat} onChange={(e) => { setCat(e.target.value); setPage(0); }}>
          <option value="">All categories</option>
          {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
        </select>
        <input className="input w-44" placeholder="Service filter" value={svc} onChange={(e) => { setSvc(e.target.value); setPage(0); }} />
      </div>

      {error && <ErrorNote message={error} />}

      <Card bodyClass="p-0">
        {loading ? (
          <div className="flex justify-center py-20 text-slate-400 dark:text-slate-500"><Spinner className="h-7 w-7" /></div>
        ) : rows.length === 0 ? (
          <div className="p-6"><EmptyState title="No documents match" hint="Upload SOPs, runbooks, RCAs, exports or logs." /></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[860px]">
              <thead className="border-b border-slate-100 dark:border-white/5 bg-slate-50/70">
                <tr>
                  <th className="th">Document</th><th className="th">Category</th><th className="th">Service</th>
                  <th className="th">Dept</th><th className="th">Ver</th><th className="th">Chunks</th>
                  <th className="th">Size</th><th className="th">Uploaded</th><th className="th text-right">Manage</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-white/5">
                {rows.map((d) => (
                  <tr key={d.id} className="hover:bg-slate-50/70 hover:dark:bg-white/5">
                    <td className="td">
                      <p className="font-medium text-slate-800 dark:text-slate-200">{d.name}</p>
                      <p className="text-[11px] text-slate-400 dark:text-slate-500">{d.document_no} · cites as <span className="font-mono text-brand-600 dark:text-brand-400">{d.citation_label}</span> · <span className="uppercase">{d.type}</span></p>
                    </td>
                    <td className="td"><Badge tone="bg-violet-50 text-violet-700 ring-1 ring-violet-200">{d.category}</Badge></td>
                    <td className="td text-slate-600 dark:text-slate-300">{d.service ?? "—"}</td>
                    <td className="td text-xs text-slate-500 dark:text-slate-400">{d.department ?? "—"}</td>
                    <td className="td text-xs text-slate-500 dark:text-slate-400">{d.version ?? "—"}</td>
                    <td className="td tabular-nums">{d.chunk_count}</td>
                    <td className="td text-xs text-slate-500 dark:text-slate-400">{fmtBytes(d.file_size)}</td>
                    <td className="td whitespace-nowrap text-xs text-slate-500 dark:text-slate-400">{fmtDate(d.created_at)}</td>
                    <td className="td text-right whitespace-nowrap">
                      <button className="text-xs font-medium text-brand-600 dark:text-brand-400 hover:underline" onClick={() => void openEdit(d)}>edit</button>
                      <button className="ml-3 text-xs font-medium text-rose-600 hover:underline" onClick={() => void remove(d)}>delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
        <span>{total} document(s)</span>
        <div className="flex items-center gap-2">
          <button className="btn-ghost px-2.5 py-1" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>← Prev</button>
          <span>page {page + 1} / {Math.max(1, Math.ceil(total / limit))}</span>
          <button className="btn-ghost px-2.5 py-1" disabled={(page + 1) * limit >= total} onClick={() => setPage((p) => p + 1)}>Next →</button>
        </div>
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={editing ? `Edit metadata — ${editing.name}` : ""}>
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-slate-500 dark:text-slate-400">Category (drives retrieval fan-out)</span>
            <select className="input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
              {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </label>
          <div className="grid grid-cols-2 gap-3">
            {[["service", "Service"], ["department", "Department"], ["version", "Version"], ["author", "Author"]].map(([k, label]) => (
              <label key={k} className="block">
                <span className="mb-1 block text-[11px] font-medium text-slate-500 dark:text-slate-400">{label}</span>
                <input className="input" value={form[k as keyof typeof form]} onChange={(e) => setForm({ ...form, [k]: e.target.value })} />
              </label>
            ))}
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button className="btn-ghost" onClick={() => setEditing(null)}>Cancel</button>
            <button className="btn-primary" onClick={() => void saveEdit()}>Save & reindex</button>
          </div>
        </div>
      </Modal>

      <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} onDone={() => { setUploadOpen(false); void load(); toast.success("Ingestion complete"); }} />
    </div>
  );
}
