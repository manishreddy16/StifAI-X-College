import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "./api.js";

const AuthContext = createContext(null);
export const useAuth = () => useContext(AuthContext);

/**
 * Holds "who is signed in" for the whole app. The browser keeps the session cookie; this only
 * remembers the *public* user info the server returned ({id,email,full_name,role}) — never a token.
 * `status`: "loading" (asking /auth/me on page load) | "ready".
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [status, setStatus] = useState("loading");

  useEffect(() => {
    let alive = true;
    api("/api/v1/auth/me")
      .then((d) => alive && setUser(d.user))
      .catch(() => alive && setUser(null))
      .finally(() => alive && setStatus("ready"));
    return () => { alive = false; };
  }, []);

  const login = useCallback(async (email, password) => {
    const d = await api("/api/v1/auth/login", { method: "POST", body: { email, password } });
    setUser(d.user);
    return d.user;
  }, []);

  const register = useCallback(async (payload) => {
    const d = await api("/api/v1/auth/register", { method: "POST", body: payload });
    setUser(d.user);
    return d.user;
  }, []);

  const logout = useCallback(async () => {
    try { await api("/api/v1/auth/logout", { method: "POST", body: {} }); } catch { /* cookie may already be gone */ }
    setUser(null);
  }, []);

  /** Called when any API answers 401: the session expired, so drop the stale user. */
  const expire = useCallback(() => setUser(null), []);

  const value = useMemo(() => ({ user, status, login, register, logout, expire }), [user, status, login, register, logout, expire]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
