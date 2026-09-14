import { useRef, useState } from "react";
import { documentApi, apiError } from "../services/api";
import { useToast } from "../hooks/useToast";
import { Modal, Spinner } from "./ui";

const CATEGORIES = ["SOP", "RUNBOOK", "JIRA_INCIDENT", "RCA", "INCIDENT_REPORT", "ARCHITECTURE",
  "DEPLOYMENT_GUIDE", "TROUBLESHOOTING_GUIDE", "KNOWLEDGE_BASE", "CHANGE_REQUEST", "POSTMORTEM", "LOG"];

export default function UploadDialog({ open, onClose, onDone }: { open: boolean; onClose: () => void; onDone: () => void }) {
  const [files, setFiles] = useState<File[]>([]);
  const [meta, setMeta] = useState({ category: "", service: "", department: "", author: "", version: "" });
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const toast = useToast();

  const submit = async () => {
    if (!files.length) { toast.error("Choose at least one file"); return; }
    setBusy(true);
    let ok = 0;
    let failed = 0;
    for (let i = 0; i < files.length; i++) {
      const f = files[i];
      setProgress(`${i + 1}/${files.length} — ${f.name}`);
      try {
        await documentApi.upload(f, meta);
        ok++;
      } catch (e) {
        failed++;
        toast.error(`${f.name}: ${apiError(e, "ingestion failed")}`);
      }
    }
    setBusy(false);
    setProgress("");
    setFiles([]);
    if (ok) onDone();
    if (ok && !failed) toast.success(`${ok} document(s) parsed, chunked, embedded and indexed`);
    else if (ok) toast.info(`${ok} ingested, ${failed} failed`);
  };

  return (
    <Modal open={open} onClose={busy ? () => undefined : onClose} title="Ingest enterprise documents" width="max-w-xl">
      <div
        className={`flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors
          ${dragOver ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-slate-50/60"}`}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          setFiles((prev) => [...prev, ...Array.from(e.dataTransfer.files)]);
        }}
      >
        <div className="text-3xl text-slate-400">⇪</div>
        <p className="text-sm text-slate-600">Drag & drop, or</p>
        <button className="btn-ghost" onClick={() => inputRef.current?.click()}>browse files</button>
        <input
          ref={inputRef}
          type="file"
          multiple
          hidden
          accept=".pdf,.docx,.doc,.txt,.md,.markdown,.html,.htm,.csv,.tsv,.xlsx,.xls,.json,.log"
          onChange={(e) => setFiles((prev) => [...prev, ...(e.target.files ? Array.from(e.target.files) : [])])}
        />
        <p className="text-[11px] text-slate-400">PDF · DOCX · DOC · TXT · MD · HTML · CSV · XLSX · JSON · LOG — max 15 MB each</p>
      </div>

      {files.length > 0 && (
        <ul className="mt-3 space-y-1">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center gap-2 rounded-md border border-slate-100 bg-white px-2.5 py-1.5 text-xs">
              <span className="truncate font-medium text-slate-700">{f.name}</span>
              <span className="text-slate-400">{(f.size / 1024).toFixed(0)} KB</span>
              <button className="ml-auto text-rose-500 hover:text-rose-700" onClick={() => setFiles(files.filter((_, j) => j !== i))} aria-label="remove">✕</button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4 grid grid-cols-2 gap-3">
        <label className="block">
          <span className="mb-1 block text-[11px] font-medium text-slate-500">Category (optional — auto-detected if blank)</span>
          <select className="input" value={meta.category} onChange={(e) => setMeta({ ...meta, category: e.target.value })}>
            <option value="">auto-detect</option>
            {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] font-medium text-slate-500">Service</span>
          <input className="input" placeholder="Payment API" value={meta.service} onChange={(e) => setMeta({ ...meta, service: e.target.value })} />
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] font-medium text-slate-500">Department</span>
          <input className="input" placeholder="SRE" value={meta.department} onChange={(e) => setMeta({ ...meta, department: e.target.value })} />
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] font-medium text-slate-500">Author / version</span>
          <div className="flex gap-2">
            <input className="input" placeholder="Operations Team" value={meta.author} onChange={(e) => setMeta({ ...meta, author: e.target.value })} />
            <input className="input w-24" placeholder="1.0" value={meta.version} onChange={(e) => setMeta({ ...meta, version: e.target.value })} />
          </div>
        </label>
      </div>

      {progress && <p className="mt-3 flex items-center gap-2 text-xs text-slate-500"><Spinner className="h-3.5 w-3.5" /> {progress}</p>}

      <div className="mt-4 flex items-center justify-between">
        <p className="text-[11px] text-slate-400">Pipeline: detect → parse → metadata → clean → chunk → embed → FAISS upsert</p>
        <button className="btn-primary" onClick={() => void submit()} disabled={busy || !files.length}>
          {busy ? <Spinner /> : "Ingest"}
        </button>
      </div>
    </Modal>
  );
}
