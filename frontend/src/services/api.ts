import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import type {
  AIResponse, AuditEntry, ChatResponse, ConfidenceDist, Conversation, ConversationDetail,
  DashboardOverview, DocumentDetail, DocumentItem, IncidentDashboard, IncidentSummary,
  KnowledgeSearchResult, RetrievalStats, RootCauseStats, SimilarIncident, SystemStats,
  UsageStats, User,
} from "../types";

// Relative base URL: works on localhost and behind the sandbox preview proxy.
export const api = axios.create({ baseURL: "/api", timeout: 120_000 });

const TOKEN_KEY = "aira_token";
const MIRROR_COOKIE = "aira_session";

/**
 * Some hosts (sandbox tunnels, corporate proxies) strip the Authorization
 * header. The API also accepts this cookie / the X-Aira-Token header, so the
 * token is mirrored into a same-site Lax cookie on every sign-in.
 */
function mirrorCookie(value: string | null) {
  try {
    if (value) {
      document.cookie = `${MIRROR_COOKIE}=${encodeURIComponent(value)}; path=/; SameSite=Lax; max-age=${
        60 * 60 * 12
      }`;
    } else {
      document.cookie = `${MIRROR_COOKIE}=; path=/; SameSite=Lax; max-age=0`;
      localStorage.removeItem(TOKEN_KEY);
    }
  } catch {
    /* storage/cookies unavailable - the in-memory token still works */
  }
}

/**
 * JWT storage that never throws.
 *
 * localStorage is unavailable in a few real contexts (sandboxed iframes without
 * same-origin access, private browsing, locked-down enterprise browsers). A
 * throwing interceptor would silently drop the Authorization header and every
 * authenticated call would come back as FastAPI's bare "Not authenticated",
 * so reads/writes are guarded and fall back to in-memory state.
 */
let memoryToken: string | null = null;
let storageBlocked = false;

const safeStorage = {
  read(): string | null {
    if (storageBlocked) return null;
    try {
      return localStorage.getItem(TOKEN_KEY);
    } catch {
      storageBlocked = true;
      return null;
    }
  },
  write(value: string): void {
    memoryToken = value;
    mirrorCookie(value);
    if (storageBlocked) return;
    try {
      localStorage.setItem(TOKEN_KEY, value);
    } catch {
      storageBlocked = true;
    }
  },
  erase(): void {
    memoryToken = null;
    mirrorCookie(null);
    if (storageBlocked) return;
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      storageBlocked = true;
    }
  },
};

export const tokenStore = {
  get: () => safeStorage.read() ?? memoryToken,
  set: (t: string) => safeStorage.write(t),
  clear: () => safeStorage.erase(),
  /** true when the browser refused persistent storage (session stays in memory) */
  get ephemeral() {
    return storageBlocked;
  },
};

api.interceptors.request.use((config) => {
  const t = tokenStore.get();
  if (t) {
    config.headers.Authorization = `Bearer ${t}`;
    (config as { airaToken?: string }).airaToken = t;
  }
  return config;
});

/**
 * Session watchdog.
 *  - `invalid` : the API answered 401 -> the token really is rejected, sign out.
 *  - `lost`    : no answer at all (server restarting/unreachable) -> keep the
 *    session and show a notice. Bouncing a signed-in user to the login screen
 *    because a process was briefly down is the worst possible UX.
 */
export type SessionEvent = { kind: "invalid" | "lost"; reason: string };
let onSessionEvent: ((ev: SessionEvent) => void) | null = null;
export const setSessionEventHandler = (fn: ((ev: SessionEvent) => void) | null) => {
  onSessionEvent = fn;
};
/** @deprecated kept so older imports keep working */
export const setUnauthorizedHandler = (fn: () => void) => {
  onSessionEvent = (ev) => { if (ev.kind === "invalid") fn(); };
};

/**
 * If a proxy ate the Authorization header, replay the request once with the
 * X-Aira-Token header (the cookie normally covers this already).
 */
api.interceptors.response.use(
  (r) => r,
  async (error: AxiosError<{ detail?: string | unknown }>) => {
    type AiraConfig = InternalAxiosRequestConfig & {
      airaToken?: string;
      _airaRetried?: boolean;
      skipAuthRedirect?: boolean;
    };
    const cfg = error.config as AiraConfig | undefined;
    if (
      error.response?.status === 401 &&
      cfg &&
      cfg.airaToken &&
      !cfg._airaRetried &&
      !cfg.skipAuthRedirect
    ) {
      cfg._airaRetried = true;
      cfg.headers?.delete?.("Authorization");
      cfg.headers?.set?.("X-Aira-Token", cfg.airaToken);
      try {
        return await api.request(cfg);
      } catch (retryErr) {
        return Promise.reject(retryErr);
      }
    }
    const status = error.response?.status;
    const skip = (error.config as { skipAuthRedirect?: boolean } | undefined)?.skipAuthRedirect;
    if (!skip && onSessionEvent) {
      if (status === 401) onSessionEvent({ kind: "invalid", reason: "Your session was rejected by the server." });
      else if (!error.response) {
        onSessionEvent({
          kind: "lost",
          reason: error.code === "ECONNABORTED"
            ? "The server took too long to answer - it may be reindexing or restarting."
            : "Cannot reach the API - it may be restarting.",
        });
      }
    }
    return Promise.reject(error);
  },
);

export const apiError = (e: unknown, fallback = "Request failed"): string => {
  if (axios.isAxiosError(e)) {
    const d = e.response?.data?.detail;
    if (!e.response) return "Backend unreachable - is the API running on port 8000?";
    if (e.code === "ECONNABORTED") return "Request timed out - the knowledge base may be rebuilding.";
    if (typeof d === "string") {
      if (d === "Not authenticated" && e.config?.url !== "/auth/login") {
        return tokenStore.ephemeral
          ? "Session expired (browser storage is blocked here, so the token is kept in memory only) - sign in again."
          : "Session expired - sign in again.";
      }
      return d;
    }
    if (Array.isArray(d) && d.length) {
      const first = d[0] as { msg?: string; loc?: (string | number)[] };
      const field = first?.loc?.filter((x) => x !== "body").join(".");
      return `${field ? field + ": " : ""}${first?.msg ?? "Validation error"}`;
    }
  }
  return fallback;
};

// ------------------------------------------------------------------- auth
export const authApi = {
  login: async (email: string, password: string) =>
    (await api.post<{ access_token: string; role: string }>("/auth/login", { email, password })).data,
  // skipAuthRedirect: typed loosely because it is consumed by an interceptor
  me: async (opts?: { tolerateExpired?: boolean }) =>
    (await api.get<User>("/auth/me", opts?.tolerateExpired ? ({ skipAuthRedirect: true } as never) : undefined)).data,
  register: async (payload: { name: string; email: string; password: string }) =>
    (await api.post<User>("/auth/register", payload)).data,
};

// ------------------------------------------------------------------- chat
export const chatApi = {
  send: async (message: string, conversationId?: number | null, followUp = false) =>
    (await api.post<ChatResponse>("/chat", {
      message,
      conversation_id: conversationId ?? null,
      follow_up: followUp,
    })).data,
  list: async (search?: string) =>
    (await api.get<Conversation[]>("/conversations", { params: search ? { search } : {} })).data,
  detail: async (id: number) => (await api.get<ConversationDetail>(`/conversations/${id}`)).data,
  rename: async (id: number, title: string) =>
    (await api.patch<Conversation>(`/conversations/${id}`, { title })).data,
  remove: async (id: number) => (await api.delete(`/conversations/${id}`)).status,
};

// --------------------------------------------------------------- incidents
export const incidentApi = {
  list: async (params: Record<string, string | number | undefined> = {}) =>
    (await api.get<{ total: number; items: IncidentSummary[] }>("/incidents", { params })).data,
  detail: async (id: number) => (await api.get<AIResponse>(`/incidents/${id}`)).data,
  analyze: async (description: string) => (await api.post<AIResponse>("/incidents", { description })).data,
  remove: async (id: number) => (await api.delete(`/incidents/${id}`)).status,
  similar: async (body: { description?: string; incident_id?: number; top_k?: number }) =>
    (await api.post<SimilarIncident[]>("/incidents/similar", body)).data,
  resolve: async (id: number, status: string, note?: string) =>
    (await api.post(`/incidents/${id}/resolution`, { resolution_status: status, note })).data,
};

// --------------------------------------------------------------- documents
export const documentApi = {
  list: async (params: Record<string, string | number | undefined> = {}) =>
    (await api.get<{ total: number; items: DocumentItem[] }>("/documents", { params })).data,
  detail: async (id: number, includeChunks = true) =>
    (await api.get<DocumentDetail>(`/documents/${id}`, { params: { include_chunks: includeChunks } })).data,
  upload: async (file: File, meta: Record<string, string> = {}) => {
    const form = new FormData();
    form.append("file", file);
    Object.entries(meta).forEach(([k, v]) => v && form.append(k, v));
    return (await api.post<DocumentItem>("/documents/upload", form)).data;
  },
  update: async (id: number, patch: Record<string, string>) =>
    (await api.patch<DocumentItem>(`/documents/${id}`, patch)).data,
  remove: async (id: number) => (await api.delete(`/documents/${id}`)).status,
  categories: async () => (await api.get<string[]>("/documents/categories")).data,
};

// --------------------------------------------------------------- knowledge
export const knowledgeApi = {
  search: async (query: string, categories?: string[], service?: string, topK = 8) =>
    (await api.post<KnowledgeSearchResult>("/knowledge/search", { query, categories, service, top_k: topK })).data,
};

// --------------------------------------------------------------- dashboard
export const dashboardApi = {
  overview: async () => (await api.get<DashboardOverview>("/dashboard/overview")).data,
  incidents: async (days = 14) => (await api.get<IncidentDashboard>("/dashboard/incidents", { params: { days } })).data,
  rootCauses: async () => (await api.get<RootCauseStats>("/dashboard/root-causes")).data,
  confidence: async () => (await api.get<ConfidenceDist>("/dashboard/confidence")).data,
  documents: async () => (await api.get<unknown>("/dashboard/documents")).data as Promise<import("../types").DocumentsStats>,
  retrieval: async () => (await api.get<RetrievalStats>("/dashboard/retrieval")).data,
  usage: async () => (await api.get<UsageStats>("/dashboard/usage")).data,
  system: async () => (await api.get<SystemStats>("/dashboard/system")).data,
  audit: async (limit = 50) => (await api.get<AuditEntry[]>("/dashboard/audit", { params: { limit } })).data,
};

// ------------------------------------------------------------------- users
export const userApi = {
  list: async (search?: string) => (await api.get<User[]>("/users", { params: { search } })).data,
  create: async (payload: { name: string; email: string; password: string; role: string }) =>
    (await api.post<User>("/users", payload)).data,
  update: async (id: number, patch: Partial<{ role: string; is_active: boolean; password: string }>) =>
    (await api.patch<User>(`/users/${id}`, patch)).data,
  remove: async (id: number) => (await api.delete(`/users/${id}`)).status,
};
