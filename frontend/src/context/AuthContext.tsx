import axios from "axios";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { apiError, authApi, setSessionEventHandler, tokenStore } from "../services/api";
import type { User } from "../types";

interface AuthCtx {
  user: User | null;
  loading: boolean;
  /** set when the API is briefly unreachable; the session is still valid */
  offlineNotice: string | null;
  retryConnection: () => Promise<boolean>;
  isAdmin: boolean;
  login: (email: string, password: string) => Promise<User>;
  logout: () => void;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [offlineNotice, setOfflineNotice] = useState<string | null>(null);
  const [bootstrapped, setBootstrapped] = useState(false);

  const logout = useCallback(() => {
    tokenStore.clear();
    setUser(null);
    setOfflineNotice(null);
  }, []);

  const loadProfile = useCallback(async () => {
    try {
      setUser(await authApi.me());
      setOfflineNotice(null);
      return true;
    } catch (err) {
      const gone = axios.isAxiosError(err) && !err.response;
      if (gone) setOfflineNotice("Cannot reach the API - it may be restarting. Your session is kept.");
      else if (axios.isAxiosError(err) && err.response?.status === 401) {
        tokenStore.clear();
        setUser(null);
      }
      return false;
    } finally {
      setLoading(false);
    }
  }, []);

  const retryConnection = useCallback(async () => loadProfile(), [loadProfile]);

  useEffect(() => {
    // Only a 401 from the *server* ends the session (see services/api.ts).
    setSessionEventHandler((ev) => {
      if (ev.kind === "invalid") {
        tokenStore.clear();
        setUser(null);
        setOfflineNotice(null);
      } else {
        setOfflineNotice(ev.reason);
      }
    });
    return () => setSessionEventHandler(null);
  }, []);

  useEffect(() => {
    if (bootstrapped) return;
    setBootstrapped(true);
    if (!tokenStore.get()) {
      setLoading(false);
      return;
    }
    void loadProfile();
  }, [bootstrapped, loadProfile]);

  const login = useCallback(async (email: string, password: string) => {
    const res = await authApi.login(email, password);
    // store before the follow-up call: /auth/me needs the bearer token
    tokenStore.set(res.access_token);
    // The login response is authoritative for *authentication*; /auth/me only
    // decorates it with name/id. If the profile call fails (API restarted with a
    // new key, storage blocked, transient proxy error) we still sign the user in
    // from the token response instead of bouncing them back to the form.
    const fallback: User = {
      id: 0,
      name: res.role === "admin" ? "Signed-in administrator" : "Signed-in engineer",
      email,
      role: res.role === "admin" ? "admin" : "user",
      is_active: true,
      created_at: new Date().toISOString(),
    };
    try {
      const me = await authApi.me({ tolerateExpired: true });
      setUser(me);
      setOfflineNotice(null);
      return me;
    } catch (err) {
      // The server rejected the fresh token (restart with a new SECRET_KEY), or
      // it is not answering at all. Neither is a credential problem: sign the
      // user in from the login response and let the profile catch up later.
      setUser(fallback);
      const unreachable = axios.isAxiosError(err) && !err.response;
      setOfflineNotice(
        unreachable
          ? "Signed in. The API is not answering right now, so your profile could not be loaded - use \"Retry\" once it is back."
          : apiError(err, "Signed in, but the profile check failed.") + " - the token was accepted, so your session was kept.",
      );
      return fallback;
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, offlineNotice, retryConnection, isAdmin: user?.role === "admin", login, logout }),
    [user, loading, offlineNotice, retryConnection, login, logout],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
