import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { authApi } from "@/services/auth";
import type { UserResponse } from "@/types/api";

interface AuthContextValue {
  user: UserResponse | null;
  isLoading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function checkSession() {
      const storedToken = localStorage.getItem("efdi_token");
      if (!storedToken) {
        return null;
      }
      // Re-verify with the server rather than trusting the cached user
      // blob -- a role change or deactivation made elsewhere should
      // take effect on next load, not just on next login.
      try {
        const freshUser = await authApi.me();
        localStorage.setItem("efdi_user", JSON.stringify(freshUser));
        return freshUser;
      } catch {
        localStorage.removeItem("efdi_token");
        localStorage.removeItem("efdi_user");
        return null;
      }
    }

    checkSession().then((resolvedUser) => {
      if (cancelled) return;
      setUser(resolvedUser);
      setIsLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const token = await authApi.login(username, password);
    localStorage.setItem("efdi_token", token.access_token);
    localStorage.setItem("efdi_user", JSON.stringify(token.user));
    setUser(token.user);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("efdi_token");
    localStorage.removeItem("efdi_user");
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

// Standard pattern: pairing a context provider with its consumer hook
// in the same file. useAuth is a hook, not a component, so Fast
// Refresh can't recognize it -- DX-only, not a correctness issue.
// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
