import type { ReactNode } from "react";

export function Card({
  title, subtitle, actions, children, className = "", bodyClass = "p-4 sm:p-5",
}: {
  title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; bodyClass?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="flex items-start justify-between gap-3 border-b border-slate-100 dark:border-white/5 px-4 py-3 sm:px-5">
          <div>
            {title && <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">{title}</h3>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

export function Badge({ tone = "bg-slate-100 dark:bg-[#212121] text-slate-700 dark:text-slate-300 ring-1 ring-slate-200 dark:ring-white/10", children, title }: {
  tone?: string; children: ReactNode; title?: string;
}) {
  return <span className={`badge ${tone}`} title={title}>{children}</span>;
}

export function Kpi({ label, value, hint, tone = "text-slate-900 dark:text-slate-100" }: {
  label: string; value: ReactNode; hint?: ReactNode; tone?: string;
}) {
  return (
    <div className="card p-4">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">{label}</p>
      <p className={`mt-1.5 text-2xl font-semibold tabular-nums ${tone}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

export function EmptyState({ title, hint, icon = "◍" }: { title: string; hint?: string; icon?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-slate-300 dark:border-neutral-700 bg-slate-50/60 dark:bg-white/5 px-6 py-10 text-center">
      <div className="text-2xl text-slate-400 dark:text-slate-500">{icon}</div>
      <p className="text-sm font-medium text-slate-600 dark:text-slate-300">{title}</p>
      {hint && <p className="max-w-md text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/40 px-3 py-2 text-sm text-rose-800" role="alert">
      {message}
    </div>
  );
}

export function Modal({ open, onClose, title, children, width = "max-w-lg" }: {
  open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; width?: string;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-slate-900/50 p-4 dark:bg-black/70 pt-[6vh]" onMouseDown={onClose}>
      <div className={`w-full ${width} rounded-xl bg-white dark:bg-[#262626] shadow-2xl`} onMouseDown={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-slate-100 dark:border-white/5 px-4 py-3">
          <h3 className="text-sm font-semibold text-slate-800 dark:text-slate-200">{title}</h3>
          <button className="rounded-md px-2 py-1 text-slate-500 dark:text-slate-400 hover:bg-slate-100 hover:dark:bg-[#2a2a2a]" onClick={onClose} aria-label="Close">✕</button>
        </header>
        <div className="p-4 sm:p-5">{children}</div>
      </div>
    </div>
  );
}
