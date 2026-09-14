import { useState } from "react";
import type { AIResponse } from "../types";
import { pct } from "../utils/format";

const SIZE = 128;
const STROKE = 11;
const R = (SIZE - STROKE) / 2;
const CIRC = 2 * Math.PI * R;

export function confidenceColor(score: number): string {
  if (score >= 0.85) return "#059669";
  if (score >= 0.65) return "#0ea5e9";
  if (score >= 0.45) return "#d97706";
  return "#e11d48";
}

export default function ConfidenceMeter({ ai, compact = false }: { ai: AIResponse; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const score = ai.confidence_score;
  const color = confidenceColor(score);
  const b = ai.confidence_breakdown;

  const signals = [
    { label: "Retrieval quality", value: b.retrieval_quality },
    { label: "Evidence validation", value: b.evidence_validation },
    { label: "Cause consistency", value: b.evidence_consistency },
    { label: "Document support", value: b.supporting_documents },
    { label: "Historical match", value: b.similar_incidents },
    { label: "Context grader", value: b.grader_score },
  ];

  return (
    <div className={compact ? "" : "card p-4"}>
      <div className="flex items-center gap-4">
        <svg width={compact ? 76 : SIZE} height={compact ? 76 : SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} className="-rotate-90">
          <circle cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" stroke="#e2e8f0" strokeWidth={STROKE} />
          <circle
            cx={SIZE / 2} cy={SIZE / 2} r={R} fill="none" stroke={color} strokeWidth={STROKE} strokeLinecap="round"
            strokeDasharray={`${CIRC * Math.max(0.02, score)} ${CIRC}`}
          />
        </svg>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">AI Confidence Score</p>
          <p className="text-2xl font-semibold tabular-nums" style={{ color }}>
            {pct(score)} <span className="text-sm font-medium text-slate-500">({ai.confidence_label})</span>
          </p>
          <p className="mt-0.5 text-[11px] leading-snug text-slate-500">
            Heuristic signal blend across retrieval, evidence validation and history — not a calibrated probability.
          </p>
          <button className="mt-1.5 text-xs font-medium text-brand-600 hover:underline" onClick={() => setOpen((o) => !o)}>
            {open ? "Hide" : "Show"} signal breakdown
          </button>
        </div>
      </div>
      {open && (
        <div className="mt-3 space-y-2 border-t border-slate-100 pt-3">
          {signals.map((s) => (
            <div key={s.label} className="flex items-center gap-3">
              <span className="w-40 shrink-0 text-xs text-slate-600">{s.label}</span>
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
                <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.round(s.value * 100)}%` }} />
              </div>
              <span className="w-10 text-right text-xs tabular-nums text-slate-500">{pct(s.value)}</span>
            </div>
          ))}
          {!!b.notes?.length && (
            <ul className="mt-1 list-inside list-disc text-[11px] text-slate-500">
              {b.notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
