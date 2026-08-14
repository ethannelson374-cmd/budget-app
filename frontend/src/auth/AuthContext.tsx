import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, apiRequest, setCsrfToken, setUnauthorizedHandler } from "../api/client";
import type { AuthSession, AuthUser, LoginResult } from "../api/types";
import { useTheme } from "../theme/ThemeContext";
import { useQueryClient } from "@tanstack/react-query";

type AuthStatus = "loading" | "authenticated" | "anonymous" | "unavailable";

interface AuthContextValue {
  user: AuthUser | null;
  status: AuthStatus;
  error: string | null;
  login: (identity: string, password: string) => Promise<{ twoFactorRequired: boolean; challengeToken: string | null }>;
  verifyTwoFactor: (challengeToken: string, code: string) => Promise<void>;
  demoLogin: () => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
  establishSession: (session: AuthSession) => void;
  sessionGeneration: number;
  isSessionCurrent: (generation: number) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const { setPreference } = useTheme();
  const queryClient = useQueryClient();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);
  const [sessionGeneration, setSessionGeneration] = useState(0);

  const advanceSessionGeneration = useCallback(() => {
    generationRef.current += 1;
    setSessionGeneration(generationRef.current);
  }, []);

  const isSessionCurrent = useCallback((generation: number) => generationRef.current === generation, []);

  const clearPrivateCaches = useCallback(() => {
    queryClient.removeQueries({
      predicate: (query) => !["setup-status", "setup-options"].includes(String(query.queryKey[0])),
    });
    queryClient.getMutationCache().clear();
  }, [queryClient]);

  const acceptSession = useCallback((session: AuthSession) => {
    advanceSessionGeneration();
    clearPrivateCaches();
    setCsrfToken(session.csrf_token);
    setPreference(session.user.settings.theme);
    setUser(session.user);
    setStatus("authenticated");
    setError(null);
  }, [advanceSessionGeneration, clearPrivateCaches, setPreference]);

  const refresh = useCallback(async () => {
    try {
      const session = await apiRequest<AuthSession>("/auth/me");
      acceptSession(session);
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status)) {
        advanceSessionGeneration();
        setCsrfToken(null);
        clearPrivateCaches();
        setUser(null);
        setStatus("anonymous");
        setError(null);
      } else {
        setError("Your session could not be verified. Check the connection and try again.");
        setStatus((current) => current === "authenticated" ? current : "unavailable");
      }
    }
  }, [acceptSession, advanceSessionGeneration, clearPrivateCaches]);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      advanceSessionGeneration();
      setCsrfToken(null);
      clearPrivateCaches();
      setUser(null);
      setStatus("anonymous");
      setError(null);
    });
    void refresh();
    return () => {
      setUnauthorizedHandler(null);
      setCsrfToken(null);
    };
  }, [advanceSessionGeneration, clearPrivateCaches, refresh]);

  const login = useCallback(async (identity: string, password: string) => {
    const result = await apiRequest<LoginResult>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ identity, password }),
    });
    if (result.two_factor_required) {
      return { twoFactorRequired: true, challengeToken: result.challenge_token };
    }
    if (!result.authenticated || !result.user || !result.csrf_token) {
      throw new ApiError("Budget could not establish your session.", { status: 503, code: "session_unavailable" });
    }
    acceptSession({ user: result.user, csrf_token: result.csrf_token });
    return { twoFactorRequired: false, challengeToken: null };
  }, [acceptSession]);

  const verifyTwoFactor = useCallback(async (challengeToken: string, code: string) => {
    const session = await apiRequest<AuthSession>("/auth/two-factor/login", {
      method: "POST",
      body: JSON.stringify({ challenge_token: challengeToken, code }),
    });
    acceptSession(session);
  }, [acceptSession]);

  const demoLogin = useCallback(async () => {
    const session = await apiRequest<AuthSession>("/auth/demo-login", { method: "POST" });
    acceptSession(session);
  }, [acceptSession]);

  const logout = useCallback(async () => {
    await apiRequest<void>("/auth/logout", { method: "POST" });
    advanceSessionGeneration();
    setCsrfToken(null);
    clearPrivateCaches();
    setUser(null);
    setStatus("anonymous");
    setError(null);
  }, [advanceSessionGeneration, clearPrivateCaches]);

  const value = useMemo(
    () => ({ user, status, error, login, verifyTwoFactor, demoLogin, logout, refresh, establishSession: acceptSession, sessionGeneration, isSessionCurrent }),
    [acceptSession, demoLogin, error, isSessionCurrent, login, logout, refresh, sessionGeneration, status, user, verifyTwoFactor],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
