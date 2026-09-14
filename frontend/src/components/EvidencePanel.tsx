import { useState } from "react";
import type { EvidenceClaim, RetrievedChunk } from "../types";
import { Badge } from "./ui";
import { evidenceTone, pct } from "../utils/format";

export function CitationChip({ label, onClick }: { label: string; onClick?: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[11px] text-slate-600
        ${onClick ? "hover:border-brand-400 hover:text-brand-600" : "cursor-default"}`}
      title={onClick ? "Show supporting excerpt" : "Evidence citation"}
    >
      {label}
    </button>
  );
}

export default function EvidencePanel({ evidence, claims }: { evidence: RetrievedChunk[]; claims?: EvidenceClaim[] }) {
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!evidence.length) {
    return (
      <p className="rounded-lg border border-dashed border-rose-300 bg-rose-50/60 px-3 py-2.5 text-sm text-rose-800">
        No supporting documents were retrieved for this incident. Treat the answer above as an escalation
        suggestion rather than a resolution.
      </p>
    );
  }

  const claimFor = (ref: string) => (claims ?? []).filter((cl) => cl.evidence.includes(ref));

  return (
    <ul className="space-y-2">
      {evidence.map((e) => {
        const related = claimFor(e.citation);
        const worst = related.some((r) => r.status === "INSUFFICIENT")
          ? "INSUFFICIENT" : related.some((r) => r.status === "PARTIALLY_SUPPORTED")
          ? "PARTIALLY_SUPPORTED" : related.length ? "SUPPORTED" : null;
        const open = expanded === e.chunk_ref;
        return (
          <li key={e.chunk_ref} className="rounded-lg border border-slate-200 bg-white">
            <button
              className="flex w-full items-center gap-2 px-3 py-2 text-left"
              onClick={() => setExpanded(open ? null : e.chunk_ref)}
            >
              <span className="font-mono text-xs font-semibold text-brand-600">{e.citation}</span>
              <Badge>{e.category}</Badge>
              {e.section && <span className="truncate text-xs text-slate-500">{e.section}</span>}
              <span className="ml-auto flex shrink-0 items-center gap-2">
                {worst && <Badge tone={evidenceTone(worst)}>{worst.replace("_", " ")}</Badge>}
                <span className="text-[11px] tabular-nums text-slate-400" title="vector similarity">sim {pct(e.score)}</span>
                <span className="text-slate-400">{open ? "▾" : "▸"}</span>
              </span>
            </button>
            {open && (
              <div className="border-t border-slate-100 bg-slate-50/70 px-3 py-2">
                <p className="text-[11px] text-slate-500">
                  {e.document_name}
                  {e.service ? ` · ${e.service}` : ""}
                  {e.page ? ` · page ${e.page}` : ""} · chunk <span className="font-mono">{e.chunk_ref}</span>
                </p>
                <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-slate-700">
                  {open ? e.text : e.text.slice(0, 240)}
                </p>
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
