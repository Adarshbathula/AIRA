import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { apiError } from "../services/api";
import { health } from "../services/system";
import { Spinner } from "../components/ui";
import ThemeToggle from "../components/ThemeToggle";

const DEMO = [
  { label: "Admin", email: "admin@aira.test", password: "Admin@12345" },
  { label: "Engineer (Priya)", email: "priya@aira.test", password: "Engineer@123" },
  { label: "Engineer (Arjun)", email: "arjun@aira.test", password: "Engineer@123" },
];

export default function Login() {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@aira.test");
  const [password, setPassword] = useState("Admin@12345");
  const [mode, setMode] = useState<"login" | "register">("login");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [apiDown, setApiDown] = useState(false);

  useEffect(() => {
    if (user) navigate("/dashboard", { replace: true });
  }, [user, navigate]);

  // A dead backend otherwise shows up as an unhelpful auth error: probe it up front.
  useEffect(() => {
    let alive = true;
    health()
      .then((h) => { if (alive && !h) setApiDown(true); })
      .catch(() => { if (alive) setApiDown(true); });
    return () => { alive = false; };
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    if (apiDown) {
      const h = await health();
      if (h) setApiDown(false);
    }
    try {
      if (mode === "register") {
        const { authApi } = await import("../services/api");
        await authApi.register({ name, email, password });
      }
      const me = await login(email, password);
      navigate(me.role === "admin" ? "/admin" : "/dashboard", { replace: true });
    } catch (err) {
      const friendly = apiError(err, "");
      setError(friendly || (err instanceof Error ? err.message : "") || "Login failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-ink-950 p-10 text-slate-200 lg:flex">
        <div>
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-lg font-bold text-white">AI</div>
            <div>
              <p className="text-lg font-semibold text-white">AI Incident Resolution Assistant</p>
              <p className="text-xs uppercase tracking-widest text-slate-400 dark:text-slate-500">Self-Healing RAG · LangGraph · FAISS</p>
            </div>
          </div>
          <p className="mt-10 max-w-md text-sm leading-relaxed text-slate-300">
            Grounded incident intelligence over your SOPs, runbooks, RCAs and incident history —
            retrieval that grades itself, rewrites its own queries when context is weak, and only
            recommends what the evidence supports.
          </p>
        </div>
        <ul className="space-y-2.5 text-sm text-slate-300">
          {[
            "Incident Analyzer extracts service, error, severity and category",
            "Context Grader + Query Rewriter retry until retrieval is GOOD",
            "Similar incident discovery via semantic search",
            "Evidence Validator flags anything the corpus cannot support",
            "Transparent AI confidence — never a fake probability",
          ].map((t) => (
            <li key={t} className="flex gap-2.5">
              <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-brand-400" /> {t}
            </li>
          ))}
        </ul>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          When no GROQ_API_KEY is configured the assistant runs in deterministic grounded mode:
          every recommendation is extracted from retrieved documents, never invented.
        </p>
      </div>

      <div className="flex items-center justify-center bg-slate-100 p-6 dark:bg-[#171717]">
        <div className="w-full max-w-md">
          <div className="mb-3 flex justify-end">
            <ThemeToggle />
          </div>
          <div className="card p-6 sm:p-8">
            <h1 className="text-xl font-semibold text-slate-900 dark:text-slate-100">{mode === "login" ? "Sign in" : "Create engineer account"}</h1>
            <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
              {mode === "login" ? "Use your workspace credentials to continue." : "New accounts receive the Engineer role."}
            </p>

            <form className="mt-6 space-y-4" onSubmit={submit}>
              {mode === "register" && (
                <label className="block">
                  <span className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-300">Full name</span>
                  <input className="input" value={name} onChange={(e) => setName(e.target.value)} required minLength={2} placeholder="Ada Lovelace" />
                </label>
              )}
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-300">Email</span>
                <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@corp.test" autoComplete="username" />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-slate-600 dark:text-slate-300">Password</span>
                <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={mode === "register" ? 8 : 1} autoComplete="current-password" />
              </label>

              {apiDown && (
                <p className="rounded-lg border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
                  The API is not reachable from this page. Start it with{" "}
                  <code className="rounded bg-amber-100 px-1 font-mono text-xs">uvicorn app.main:app --port 8000</code>{" "}
                  from <code className="rounded bg-amber-100 px-1 font-mono text-xs">backend/</code>, then sign in again.
                </p>
              )}
              {error && <p className="rounded-lg border border-rose-200 dark:border-rose-900 bg-rose-50 dark:bg-rose-950/40 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">{error}</p>}

              <button className="btn-primary w-full justify-center" disabled={busy}>
                {busy && <Spinner />} {mode === "login" ? "Sign in" : "Register & sign in"}
              </button>
            </form>

            <div className="mt-5 border-t border-slate-100 dark:border-white/5 pt-4">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">Demo accounts</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {DEMO.map((d) => (
                  <button
                    key={d.email}
                    type="button"
                    className="rounded-lg border border-slate-200 dark:border-white/10 bg-slate-50 dark:bg-[#171717] px-2.5 py-1.5 text-left text-xs hover:border-brand-400"
                    onClick={() => { setMode("login"); setEmail(d.email); setPassword(d.password); setError(""); }}
                  >
                    <span className="font-semibold text-slate-700 dark:text-slate-300">{d.label}</span>
                    <span className="block font-mono text-[10px] text-slate-500 dark:text-slate-400">{d.email}</span>
                  </button>
                ))}
              </div>
              <button className="mt-3 text-xs font-medium text-brand-600 dark:text-brand-400 hover:underline" onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(""); }}>
                {mode === "login" ? "Need an engineer account? Register" : "Back to sign in"}
              </button>
            </div>
          </div>
          <p className="mt-4 text-center text-[11px] text-slate-400 dark:text-slate-500">JWT auth · bcrypt password hashing · role-based access control</p>
        </div>
      </div>
    </div>
  );
}
