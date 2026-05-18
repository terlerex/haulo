import { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { api } from '../api.js';

const AuthCtx = createContext(null);
const AUTH_TIMEOUT_MS = 5000;

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  const [authError, setAuthError] = useState(null); // 'timeout' | 'network' | null

  const refresh = useCallback(async () => {
    setAuthError(null);
    setChecking(true);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), AUTH_TIMEOUT_MS);
    try {
      const res = await fetch('/api/auth/me', {
        credentials: 'include',
        signal: controller.signal,
      });
      if (res.ok) {
        const u = await res.json();
        setUser(u);
        return u;
      }
      setUser(null);
      return null;
    } catch (e) {
      setUser(null);
      setAuthError(e.name === 'AbortError' ? 'timeout' : 'network');
      return null;
    } finally {
      clearTimeout(timer);
      setChecking(false);
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const login = async (username, password) => {
    await api.login(username, password);
    return refresh();
  };

  const logout = async () => {
    try { await api.logout(); } catch (_) {}
    setUser(null);
  };

  return (
    <AuthCtx.Provider value={{ user, checking, login, logout, refresh, authError }}>
      {children}
    </AuthCtx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthCtx);
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider');
  return ctx;
}
