import { useState } from "react";
import type { NodeTrace } from "../types";

const LABELS: Record<string, string> = {
  incident_analyzer: "Incident Analyzer",
  query_constructor: "Query Construction",
  retriever: "FAISS Retrieval",
  context_grader: "Context Grader",
  query_rewriter: "Query Rewriter (self-heal)",
  similar_incidents: "Similar Incident Search",
  root_cause: "Root Cause Generator",
  recommendations: "Troubleshooting Generator",
  evidence_validator: "Evidence Validator",
  confidence: "Confidence Estimator",
  summarizer: "Incident Summarizer",
  assemble: "Final Response",
};

const tone = (s: NodeTrace["status"]) =>
  s === "ok" ? "bg-emerald-500" : s === "retry" ? "bg-amber-500" : s === "skipped" ? "bg-slate-300" : "bg-rose-500";

/** User-facing pipeline trace: *what the system did*, not its internal reasoning. */
export default function FlowSteps({ trace, defaultOpen = false }: { trace: NodeTrace[]; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const retries = trace.filter((t) => t.status === "retry").length;
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50/70">
      <button
        className="flex w-full items-center justify-between px-3 py-2 text-xs font-medium text-slate-600 hover:text-slate-900"
        onClick={() => setOpen((o) => !o)}
      >
        <span>
          LangGraph workflow trace {open ? "▾" : "▸"}
          {retries > 0 && <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700">self-healed ×{retries}</span>}
        </span>
        <span className="tabular-nums text-slate-400">{trace.reduce((a, t) => a + (t.ms || 0), 0).toFixed(0)} ms</span>
      </button>
      {open && (
        <ol className="space-y-1.5 px-3 pb-3">
          {trace.map((t, i) => (
            <li key={`${t.node}-${i}`} className="flex items-start gap-2 text-xs">
              <span className={`mt-1 h-2 w-2 shrink-0 rounded-full ${tone(t.status)}`} />
              <span className="w-44 shrink-0 font-medium text-slate-700">{LABELS[t.node] ?? t.node}</span>
              <span className="flex-1 leading-relaxed text-slate-500">
                {t.detail ?? "—"}
                {!!t.ms && <span className="ml-1.5 tabular-nums text-slate-400">({t.ms.toFixed(0)}ms)</span>}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
