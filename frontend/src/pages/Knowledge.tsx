import { useCallback, useEffect, useMemo, useState } from "react";
import { documentApi, knowledgeApi, apiError } from "../services/api";
import { useAuth } from "../context/AuthContext";
import type { DocumentItem, KnowledgeSearchResult } from "../types";
import { Badge, Card, EmptyState, ErrorNote, Modal, Spinner } from "../components/ui";
import { fmtDate, fmtBytes, pct } from "../utils/format";
import { useToast } from "../hooks/useToast";
import UploadDialog from "../components/UploadDialog";

export default function Knowledge() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const [docs, setDocs] = useState<DocumentItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [service, setService] = useState("");
  const [type, setType] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [detail, setDetail] = useState<Awaited<ReturnType<typeof documentApi.detail>> | null>(null);
  const [results, setResults] = useState<KnowledgeSearchResult | null>(null);
  const [searching, setSearching] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await documentApi.list({
        limit: 50,
        search: q || undefined, category: category || undefined,
        service: service || undefined, type: type || undefined,
      });
      setDocs(res.items); setTotal(res.total);
    } catch (e) {
      setError(apiError(e, "Could not load documents"));
    } finally {
      setLoading(false);
    }
  }, [q, category, service, type]);

  useEffect(() => {
    const t = window.setTimeout(() => void load(), 220);
    return () => window.clearTimeout(t);
  }, [load]);

  const services = useMemo(() => Array.from(new Set(docs.map((d) => d.service).filter(Boolean))) as string[], [docs]);

  const semanticSearch = async () => {
    if (q.trim().length < 3) { toast.error("Type a query (3+ characters) first"); return; }
    setSearching(true);
    try {
      setResults(await knowledgeApi.search(q.trim(), category ? [category] : undefined, service || undefined, 12));
    } catch (e) {
      toast.error(apiError(e, "Search failed"));
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Enterprise knowledge base</h2>
          <p className="text-sm text-slate-500">
            SOPs, runbooks, RCAs, incident reports, architecture docs and logs that ground every AI answer.
          </p>
        </div>
        {isAdmin && <button className="btn-primary" onClick={() => setUploadOpen(true)}>⇪ Upload document</button>}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input
          className="input w-80"
          placeholder="Keyword search, or use for semantic search…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select className="input w-48" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {["SOP", "RUNBOOK", "JIRA_INCIDENT", "RCA", "INCIDENT_REPORT", "ARCHITECTURE", "DEPLOYMENT_GUIDE",
            "TROUBLESHOOTING_GUIDE", "KNOWLEDGE_BASE", "CHANGE_REQUEST", "POSTMORTEM", "LOG"].map((c) => <option key={c}>{c}</option>)}
        </select>
        <select className="input w-44" value={service} onChange={(e) => setService(e.target.value)}>
          <option value="">All services</option>
          {services.map((s) => <option key={s}>{s}</option>)}
        </select>
        <select className="input w-28" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All types</option>
          {["pdf", "docx", "txt", "md", "html", "csv", "json", "log", "xlsx"].map((t) => <option key={t}>{t}</option>)}
        </select>
        <button className="btn-primary" onClick={() => void semanticSearch()} disabled={searching}>
          {searching ? <Spinner /> : "◉ Semantic search"}
        </button>
      </div>

      {error && <ErrorNote message={error} />}

      {results && (
        <Card title={`Semantic matches for “${results.query}”`} subtitle={`${results.chunks.length} chunks · ${results.took_ms} ms · categories: ${Object.entries(results.by_category).map(([k, v]) => `${k}(${v})`).join(", ") || "none"}`}
          actions={<button className="text-xs font-medium text-slate-400 hover:text-slate-700" onClick={() => setResults(null)}>close</button>}>
          {results.chunks.length ? (
            <ul className="space-y-2">
              {results.chunks.map((c) => (
                <li key={c.chunk_ref} className="rounded-lg border border-slate-100 px-3 py-2">
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="font-mono font-semibold text-brand-600">{c.citation}</span>
                    <Badge>{c.category}</Badge>
                    {c.service && <Badge tone="bg-slate-100 text-slate-600 ring-1 ring-slate-200">{c.service}</Badge>}
                    {c.section && <span className="text-slate-500">{c.section}</span>}
                    <span className="ml-auto tabular-nums text-slate-400">sim {pct(c.score)}</span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-slate-600">{c.text}</p>
                </li>
              ))}
            </ul>
          ) : <EmptyState title="No relevant chunks" hint="Try fewer words or a different category filter." />}
        </Card>
      )}

      <Card bodyClass="p-0">
        {loading ? (
          <div className="flex justify-center py-20 text-slate-400"><Spinner className="h-7 w-7" /></div>
        ) : docs.length === 0 ? (
          <div className="p-6"><EmptyState title="No documents found" hint={isAdmin ? "Upload enterprise documents to power the assistant." : "Ask an administrator to seed the knowledge base."} /></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px]">
              <thead className="border-b border-slate-100 bg-slate-50/70">
                <tr>
                  <th className="th">Document</th><th className="th">Category</th><th className="th">Service</th>
                  <th className="th">Department</th><th className="th">Type</th><th className="th">Chunks</th>
                  <th className="th">Size</th><th className="th">Updated</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {docs.map((d) => (
                  <tr key={d.id} className="cursor-pointer hover:bg-slate-50" onClick={() => void documentApi.detail(d.id).then(setDetail)}>
                    <td className="td">
                      <p className="font-medium text-slate-800">{d.name}</p>
                      <p className="text-[11px] text-slate-400">{d.document_no} · cite as <span className="font-mono text-brand-600">{d.citation_label}</span></p>
                    </td>
                    <td className="td"><Badge tone="bg-violet-50 text-violet-700 ring-1 ring-violet-200">{d.category}</Badge></td>
                    <td className="td text-slate-600">{d.service ?? "—"}</td>
                    <td className="td text-xs text-slate-500">{d.department ?? "—"}</td>
                    <td className="td"><Badge tone="bg-slate-100 text-slate-600 ring-1 ring-slate-200 uppercase">{d.type}</Badge></td>
                    <td className="td tabular-nums text-slate-600">{d.chunk_count}</td>
                    <td className="td text-xs text-slate-500">{fmtBytes(d.file_size)}</td>
                    <td className="td whitespace-nowrap text-xs text-slate-500">{fmtDate(d.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="border-t border-slate-100 px-4 py-2 text-[11px] text-slate-400">{total} document(s) · click a row to inspect extracted chunks</p>
          </div>
        )}
      </Card>

      <Modal open={!!detail} onClose={() => setDetail(null)} title={detail ? `${detail.name} (${detail.document_no})` : ""} width="max-w-3xl">
        {detail && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2 text-xs text-slate-500">
              <Badge tone="bg-violet-50 text-violet-700 ring-1 ring-violet-200">{detail.category}</Badge>
              {detail.service && <Badge>{detail.service}</Badge>}
              {detail.department && <Badge>{detail.department}</Badge>}
              {detail.version && <Badge>v{detail.version}</Badge>}
              {detail.author && <Badge>{detail.author}</Badge>}
              <Badge>{detail.chunk_count} chunks</Badge>
              {detail.page_count && <Badge>{detail.page_count} pages</Badge>}
            </div>
            <div className="max-h-[52vh] space-y-2 overflow-y-auto rounded-lg border border-slate-100 bg-slate-50/50 p-2">
              {detail.chunks.map((c) => (
                <div key={c.chunk_ref} className="rounded-md bg-white p-2.5 shadow-sm ring-1 ring-slate-100">
                  <p className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-slate-400">
                    <span className="font-mono">{c.chunk_ref}</span>
                    {c.section && <span>· {c.section}</span>}
                    {c.page && <span>· p.{c.page}</span>}
                    <span className="ml-auto">≈{c.tokens} tokens</span>
                  </p>
                  <p className="mt-1 whitespace-pre-wrap text-xs leading-relaxed text-slate-700">{c.preview}{c.preview.length >= 600 ? " …" : ""}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </Modal>

      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onDone={() => { setUploadOpen(false); void load(); toast.success("Document ingested and indexed"); }}
      />
    </div>
  );
}
