import { Link } from "react-router-dom";
import type { AIResponse } from "../types";
import { causeTone, evidenceTone, pct, qualityTone, severityTone } from "../utils/format";
import ConfidenceMeter from "./ConfidenceMeter";
import EvidencePanel from "./EvidencePanel";
import FlowSteps from "./FlowSteps";
import { Badge } from "./ui";

export default function AssistantResponse({ ai, showTrace = true }: { ai: AIResponse; showTrace?: boolean }) {
  const a = ai.analysis;
  const hasAnswer = !ai.insufficient_evidence;

  return (
    <div className="space-y-4">
      {/* header row */}
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-md bg-ink-900 px-2 py-1 font-mono text-[11px] font-semibold text-white">{ai.public_id}</span>
        {a.service && <Badge tone="bg-brand-50 text-brand-600 dark:text-brand-400 ring-1 ring-brand-100">{a.service}</Badge>}
        {a.error && <Badge tone="bg-slate-100 dark:bg-[#212121] text-slate-700 dark:text-slate-300 ring-1 ring-slate-200 dark:ring-white/10">{a.error}</Badge>}
        {a.environment && <Badge>{a.environment}</Badge>}
        {a.event && <Badge>event: {a.event}</Badge>}
        <Badge tone={severityTone(a.severity)}>{a.severity}</Badge>
        <Badge tone="bg-violet-50 text-violet-700 ring-1 ring-violet-200">{a.category}</Badge>
        <span className="ml-auto flex flex-wrap items-center gap-2 text-[11px] text-slate-500 dark:text-slate-400">
          <Badge tone={qualityTone(ai.retrieval_quality)}>Retrieval: {ai.retrieval_quality}</Badge>
          <Badge tone={evidenceTone(ai.evidence_status)}>Evidence: {ai.evidence_status.replace("_", " ")}</Badge>
          <Badge tone="bg-slate-100 dark:bg-[#212121] text-slate-600 dark:text-slate-300 ring-1 ring-slate-200 dark:ring-white/10">
            {ai.embedding_backend === "fastembed" ? "HF MiniLM embeddings" : "hashed embeddings"}
            {ai.llm_used ? " · Groq LLM" : " · grounded mode"}
          </Badge>
          <Link to={`/incidents/${ai.incident_id}`} className="font-medium text-brand-600 dark:text-brand-400 hover:underline">Full record →</Link>
        </span>
      </div>

      {/* summary */}
      <p className="text-sm leading-relaxed text-slate-700 dark:text-slate-300">{ai.summary || a.keywords?.join(", ")}</p>

      {!hasAnswer && (
        <div className="rounded-lg border border-rose-300 bg-rose-50 dark:bg-rose-950/40 p-3.5">
          <p className="text-sm font-semibold text-rose-800">Insufficient Evidence</p>
          <p className="mt-1 text-sm text-rose-700 dark:text-rose-300">
            The knowledge base does not contain enough relevant information to confidently recommend a resolution.
          </p>
          <p className="mt-2 text-sm text-rose-700 dark:text-rose-300">
            <span className="font-semibold">Suggested Action:</span> Escalate to an SRE/IT operations engineer and
            review the incident manually.
          </p>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {/* causes + steps */}
        <div className="space-y-4 lg:col-span-2">
          <div className="card p-4">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Probable Root Causes</h4>
            <ol className="mt-2 space-y-2.5">
              {ai.root_causes.map((c, i) => (
                <li key={`${c.label}-${i}`} className="flex gap-3">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 dark:bg-[#212121] text-[11px] font-bold text-slate-600 dark:text-slate-300">{i + 1}</span>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-slate-800 dark:text-slate-200">
                      {c.label}{" "}
                      <span className={`badge ${causeTone(c.status)}`}>{c.status === "INSUFFICIENT_EVIDENCE" ? "NO EVIDENCE" : c.status}</span>{" "}
                      <span className="text-xs font-normal text-slate-500 dark:text-slate-400">probability: {c.probability}</span>
                    </p>
                    <p className="mt-0.5 text-[13px] leading-relaxed text-slate-600 dark:text-slate-300">{c.description}</p>
                    {!!c.evidence.length && (
                      <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
                        Evidence: {c.evidence.map((e) => <span key={e} className="mr-1 font-mono text-brand-600 dark:text-brand-400">{e}</span>)}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </div>

          <div className="card p-4">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
              Recommended Troubleshooting
            </h4>
            {ai.troubleshooting.length ? (
              <ol className="mt-2 space-y-2">
                {ai.troubleshooting.map((s, i) => (
                  <li key={i} className="flex items-start gap-3 rounded-lg border border-slate-100 dark:border-white/5 bg-slate-50/60 dark:bg-white/5 px-3 py-2">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-600 text-[11px] font-bold text-white">{i + 1}</span>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm text-slate-800 dark:text-slate-200">{s.step}</p>
                      <p className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px]">
                        {s.evidence.map((ev) => (
                          <span key={ev} className="rounded bg-white dark:bg-[#262626] px-1.5 py-0.5 font-mono text-slate-500 dark:text-slate-400 ring-1 ring-slate-200 dark:ring-white/10">{ev}</span>
                        ))}
                        <span className={`badge ml-auto ${evidenceTone(s.evidence_status)}`}>{s.evidence_status.replace("_", " ")}</span>
                      </p>
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                No evidence-backed procedure was found — do not improvise; escalate instead.
              </p>
            )}
          </div>

          <div className="card p-4">
            <div className="flex items-center justify-between">
              <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Supporting Evidence</h4>
              <span className="text-[11px] text-slate-500 dark:text-slate-400">
                {ai.supporting_document_count} documents · {ai.retrieval_attempts} retrieval attempt{ai.retrieval_attempts > 1 ? "s" : ""}
              </span>
            </div>
            <div className="mt-2">
              <EvidencePanel evidence={ai.evidence} claims={ai.evidence_claims} />
            </div>
          </div>
        </div>

        {/* right rail */}
        <div className="space-y-4">
          <ConfidenceMeter ai={ai} />

          <div className="card p-4">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Similar Incidents</h4>
            {ai.similar_incidents.length ? (
              <ul className="mt-2 space-y-2">
                {ai.similar_incidents.map((s) => (
                  <li key={s.public_id} className="rounded-lg border border-slate-100 dark:border-white/5 bg-slate-50/70 px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-semibold text-slate-700 dark:text-slate-300">{s.public_id}</span>
                      {s.severity && <Badge tone={severityTone(s.severity)}>{s.severity}</Badge>}
                      <span className="ml-auto text-xs font-semibold tabular-nums text-emerald-700 dark:text-emerald-300">{pct(s.similarity)}</span>
                    </div>
                    <div className="mt-1 h-1 overflow-hidden rounded bg-slate-200 dark:bg-[#2f2f2f]">
                      <div className="h-full rounded bg-emerald-500" style={{ width: `${Math.round(s.similarity * 100)}%` }} />
                    </div>
                    <p className="mt-1.5 line-clamp-2 text-xs text-slate-600 dark:text-slate-300">{s.title}</p>
                    {s.root_cause && <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">cause: {s.root_cause}</p>}
                    {s.resolution && <p className="text-[11px] text-emerald-700 dark:text-emerald-300">fix: {s.resolution}</p>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-xs text-slate-500 dark:text-slate-400">
                No sufficiently similar historical incident found (similarity threshold 45%). First occurrence —
                capture a postmortem after resolution.
              </p>
            )}
          </div>

          <div className="card p-4">
            <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Retrieval Detail</h4>
            <dl className="mt-2 space-y-1.5 text-xs">
              <Row k="Quality" v={<Badge tone={qualityTone(ai.retrieval_quality)}>{ai.retrieval_quality}</Badge>} />
              <Row k="Attempts" v={ai.retrieval_attempts} />
              <Row k="Grader score" v={ai.retrieval.grader ? pct(ai.retrieval.grader.score) : "—"} />
              <Row k="Top similarity" v={ai.retrieval.scores.length ? pct(Math.max(...ai.retrieval.scores)) : "—"} />
              <Row k="Feedback" v={ai.retrieval.grader?.feedback || "—"} />
            </dl>
            {!!ai.retrieval.queries.length && (
              <details className="mt-2">
                <summary className="cursor-pointer text-[11px] font-medium text-slate-500 dark:text-slate-400">queries used</summary>
                <ol className="mt-1 space-y-1">
                  {ai.retrieval.queries.map((q, i) => (
                    <li key={i} className="rounded bg-slate-50 dark:bg-[#171717] px-2 py-1 font-mono text-[10px] leading-relaxed text-slate-600 dark:text-slate-300">
                      {i + 1}. {q}
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </div>

          {showTrace && <FlowSteps trace={ai.trace} />}
        </div>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-slate-500 dark:text-slate-400">{k}</dt>
      <dd className="text-right font-medium text-slate-700 dark:text-slate-300">{v}</dd>
    </div>
  );
}
