import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { health } from "../services/system";
import { Badge } from "../components/ui";

const NAV = [
  { to: "/dashboard", label: "Dashboard", icon: "▦" },
  { to: "/assistant", label: "Incident Assistant", icon: "◈" },
  { to: "/history", label: "Conversations", icon: "≡" },
  { to: "/incidents", label: "Incidents", icon: "⚠" },
  { to: "/knowledge", label: "Knowledge Base", icon: "⌘" },
];
const ADMIN_NAV = [
  { to: "/admin", label: "Admin Overview", icon: "◎" },
  { to: "/admin/documents", label: "Document Manager", icon: "⇪" },
  { to: "/admin/users", label: "User Management", icon: "☺" },
];

export default function AppLayout() {
  const { user, logout, isAdmin, offlineNotice, retryConnection } = useAuth();
  const [retrying, setRetrying] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const [sys, setSys] = useState<{ llm: string; vectors: number; embeddings: string } | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    void health().then((h) => {
      if (!alive || !h) return;
      setSys({
        llm: h.llm?.mode ?? "unknown",
        vectors: h.vector_store?.vectors ?? 0,
        embeddings: h.embeddings?.provider ?? "?",
      });
    }).catch(() => undefined);
    return () => { alive = false; };
  }, [location.pathname]);

  useEffect(() => setOpen(false), [location.pathname]);

  const retry = async () => {
    setRetrying(true);
    await retryConnection();
    setRetrying(false);
  };

  return (
    <div className="flex min-h-screen">
      <aside className={`fixed inset-y-0 left-0 z-30 w-64 transform bg-ink-950 transition-transform lg:static lg:translate-x-0 ${open ? "translate-x-0" : "-translate-x-full"}`}>
        <div className="flex h-16 items-center gap-2.5 border-b border-white/10 px-4">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-600 font-bold text-white">AI</div>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-white">Incident Resolution</p>
            <p className="text-[10px] uppercase tracking-wider text-slate-400">Self-Healing RAG · LangGraph</p>
          </div>
        </div>

        <nav className="space-y-0.5 px-2 py-4">
          <p className="px-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-slate-500">Workspace</p>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => `sidebar-link ${isActive ? "sidebar-link-active" : ""}`}>
              <span className="text-base leading-none">{n.icon}</span> {n.label}
            </NavLink>
          ))}
          {isAdmin && (
            <>
              <p className="px-3 pb-1 pt-4 text-[10px] font-semibold uppercase tracking-widest text-slate-500">Administration</p>
              {ADMIN_NAV.map((n) => (
                <NavLink key={n.to} to={n.to} className={({ isActive }) => `sidebar-link ${isActive ? "sidebar-link-active" : ""}`}>
                  <span className="text-base leading-none">{n.icon}</span> {n.label}
                </NavLink>
              ))}
            </>
          )}
        </nav>

        <div className="mx-3 mt-2 rounded-lg bg-ink-900 p-3 text-[11px] leading-relaxed text-slate-400">
          <p className="font-semibold text-slate-300">Runtime</p>
          {sys ? (
            <ul className="mt-1 space-y-0.5">
              <li>LLM: <span className="text-slate-200">{sys.llm === "llm-grounded" ? "Groq (grounded)" : "deterministic grounded"}</span></li>
              <li>Embeddings: <span className="text-slate-200">{sys.embeddings}</span></li>
              <li>FAISS vectors: <span className="text-slate-200 tabular-nums">{sys.vectors}</span></li>
            </ul>
          ) : <p className="mt-1">connecting to /api/health …</p>}
        </div>

        <button
          className="sidebar-link mx-2 mt-3 w-[calc(100%-1rem)]"
          onClick={() => { logout(); navigate("/login"); }}
        >
          <span className="text-base leading-none">⎋</span> Sign out
        </button>
      </aside>

      {open && <div className="fixed inset-0 z-20 bg-slate-900/40 lg:hidden" onClick={() => setOpen(false)} />}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-16 items-center gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur sm:px-6">
          <button className="rounded-md border border-slate-200 px-2.5 py-1.5 text-slate-600 lg:hidden" onClick={() => setOpen((o) => !o)} aria-label="Menu">
            ☰
          </button>
          <h1 className="truncate text-sm font-semibold text-slate-800">
            {NAV.concat(isAdmin ? ADMIN_NAV : []).find((n) => location.pathname.startsWith(n.to))?.label ?? "AI Incident Resolution Assistant"}
          </h1>
          <div className="ml-auto flex items-center gap-3">
            <Badge tone="bg-slate-100 text-slate-600 ring-1 ring-slate-200">
              {user?.role === "admin" ? "ADMIN" : "ENGINEER"}
            </Badge>
            <div className="hidden items-center gap-2 sm:flex">
              <div className="flex h-8 w-8 items-center justify-center rounded-full bg-ink-900 text-xs font-bold text-white">
                {user?.name?.split(" ").map((w) => w[0]).join("").slice(0, 2).toUpperCase()}
              </div>
              <div className="leading-tight">
                <p className="text-xs font-semibold text-slate-800">{user?.name}</p>
                <p className="text-[10px] text-slate-500">{user?.email}</p>
              </div>
            </div>
          </div>
        </header>

        <main className="min-w-0 flex-1 p-4 sm:p-6">
            {offlineNotice && (
              <div className="mb-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                <span aria-hidden>⚠</span>
                <p className="flex-1">{offlineNotice}</p>
                <button
                  onClick={retry}
                  disabled={retrying}
                  className="rounded-md border border-amber-300 bg-white px-2 py-0.5 text-xs font-medium text-amber-800 hover:bg-amber-100 disabled:opacity-60"
                >
                  {retrying ? "Retrying…" : "Retry"}
                </button>
              </div>
            )}
            <Outlet />
        </main>
      </div>
    </div>
  );
}
