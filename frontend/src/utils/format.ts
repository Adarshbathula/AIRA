export const pct = (v: number | null | undefined, digits = 0): string =>
  v == null ? "—" : `${(v * 100).toFixed(digits)}%`;

export const fmtDate = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  if (Number.isNaN(d.getTime())) return iso.slice(0, 10);
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
};

export const relTime = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z").getTime();
  const diff = Date.now() - d;
  if (Number.isNaN(d)) return "—";
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(d).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
};

export const fmtBytes = (n: number): string => {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
};

export const severityTone = (s: string | null | undefined): string =>
  ({ P0: "bg-rose-100 text-rose-700 ring-1 ring-rose-200", P1: "bg-orange-100 text-orange-700 ring-1 ring-orange-200",
     P2: "bg-amber-100 text-amber-700 ring-1 ring-amber-200", P3: "bg-sky-100 text-sky-700 ring-1 ring-sky-200",
     P4: "bg-slate-100 text-slate-600 ring-1 ring-slate-200" }[s ?? ""] ?? "bg-slate-100 text-slate-600 ring-1 ring-slate-200");

export const qualityTone = (q: string | null | undefined): string =>
  ({ GOOD: "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200",
     FAIR: "bg-amber-100 text-amber-700 ring-1 ring-amber-200",
     POOR: "bg-rose-100 text-rose-700 ring-1 ring-rose-200" }[q ?? ""] ?? "bg-slate-100 text-slate-600");

export const evidenceTone = (s: string | null | undefined): string =>
  ({ SUPPORTED: "bg-emerald-100 text-emerald-700 ring-1 ring-emerald-200",
     PARTIALLY_SUPPORTED: "bg-amber-100 text-amber-800 ring-1 ring-amber-200",
     INSUFFICIENT: "bg-rose-100 text-rose-700 ring-1 ring-rose-200" }[s ?? ""] ?? "bg-slate-100 text-slate-600");

export const causeTone = (s: string | null | undefined): string =>
  ({ CONFIRMED: "bg-emerald-600 text-white", PROBABLE: "bg-brand-600 text-white",
     POSSIBLE: "bg-slate-500 text-white", INSUFFICIENT_EVIDENCE: "bg-rose-600 text-white" }[s ?? ""] ?? "bg-slate-400 text-white");

export const CATEGORY_COLORS = [
  "#2b5ac4", "#0ea5e9", "#8b5cf6", "#f59e0b", "#10b981", "#ef4444", "#64748b", "#d946ef", "#14b8a6", "#f97316", "#6366f1",
];
