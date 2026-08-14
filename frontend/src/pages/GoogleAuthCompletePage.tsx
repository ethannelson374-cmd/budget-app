import { useEffect, useRef } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "../components/Brand";
import { PageLoading } from "../components/States";

export function GoogleAuthCompletePage() {
  const { status, refresh } = useAuth();
  const [params] = useSearchParams();
  const refreshed = useRef(false);
  const rawNext = params.get("next");
  const next = rawNext?.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/dashboard";

  useEffect(() => {
    if (!refreshed.current) {
      refreshed.current = true;
      void refresh();
    }
  }, [refresh]);

  if (status === "authenticated") return <Navigate to={next} replace />;
  if (status === "anonymous" && refreshed.current) return <Navigate to="/login?auth_error=google_provider_error" replace />;
  return <main className="centered-page"><Brand linked={false} /><PageLoading label="Finishing Google sign-in" /></main>;
}
