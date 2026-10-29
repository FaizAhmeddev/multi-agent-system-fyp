import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, hasSession, login as apiLogin, logout as apiLogout, refreshSession, setSignedOutHandler, type User } from "./api";

interface AuthState {
  user: User | null;
  ready: boolean;
  signIn: (email: string, password: string) => Promise<User>;
  signOut: () => Promise<void>;
  reload: () => Promise<void>;
  has: (...roles: string[]) => boolean;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const reload = useCallback(async () => {
    try {
      setUser(await api<User>("/api/auth/me"));
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    setSignedOutHandler(() => {
      setUser(null);
      qc.clear();
    });
    (async () => {
      if (hasSession() && (await refreshSession())) await reload();
      setReady(true);
    })();
  }, [qc, reload]);

  const signIn = useCallback(async (email: string, password: string) => {
    const u = await apiLogin(email, password);
    qc.clear();
    setUser(u);
    return u;
  }, [qc]);

  const signOut = useCallback(async () => {
    await apiLogout();
    qc.clear();
    setUser(null);
  }, [qc]);

  const has = useCallback(
    (...roles: string[]) => !!user && (user.roles.includes("admin") || roles.some((r) => user.roles.includes(r))),
    [user],
  );

  return <Ctx.Provider value={{ user, ready, signIn, signOut, reload, has }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export const STAFF = ["hr", "it", "finance", "employee"];
