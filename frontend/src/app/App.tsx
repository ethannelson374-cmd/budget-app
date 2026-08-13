import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ApiError } from "../api/client";
import { useSetupStatus } from "../api/queries";
import { useAuth } from "../auth/AuthContext";
import { AppShell } from "../components/AppShell";
import { Brand } from "../components/Brand";
import { ErrorState, PageLoading } from "../components/States";
import { AccountsPage } from "../pages/AccountsPage";
import { DashboardPage } from "../pages/DashboardPage";
import { LoginPage } from "../pages/LoginPage";
import { PlaidOAuthPage } from "../pages/PlaidOAuthPage";
import { SettingsPage } from "../pages/SettingsPage";
import { RecurringPage } from "../pages/RecurringPage";
import { SetupPage } from "../pages/SetupPage";
import { TransactionsPage } from "../pages/TransactionsPage";

function SetupError({ error, retry }: { error: Error; retry: () => void }) {
  const apiError = error instanceof ApiError ? error : null;
  return (
    <main className="centered-page error-page">
      <Brand linked={false} />
      <ErrorState title="Budget is unavailable" message={error.message || "The application status could not be loaded."} requestId={apiError?.requestId} onRetry={retry} />
    </main>
  );
}

function AuthUnavailable() {
  const { error, refresh } = useAuth();
  return (
    <main className="centered-page error-page">
      <Brand linked={false} />
      <ErrorState title="Your session could not be verified" message={error ?? "Check the connection and try again."} onRetry={() => void refresh()} />
    </main>
  );
}

function RootRedirect() {
  const setup = useSetupStatus();
  const { status } = useAuth();
  if (setup.isPending || status === "loading") return <PageLoading />;
  if (setup.isError) return <SetupError error={setup.error} retry={() => void setup.refetch()} />;
  if (!setup.data.initialized) return <Navigate to="/setup" replace />;
  if (status === "unavailable") return <AuthUnavailable />;
  return <Navigate to={status === "authenticated" ? "/dashboard" : "/login"} replace />;
}

function SetupRoute() {
  const setup = useSetupStatus();
  const { status } = useAuth();
  if (setup.isPending || status === "loading") return <PageLoading label="Checking installation" />;
  if (setup.isError) return <SetupError error={setup.error} retry={() => void setup.refetch()} />;
  if (setup.data.initialized) return <Navigate to={status === "authenticated" ? "/dashboard" : "/login"} replace />;
  return <SetupPage status={setup.data} />;
}

function LoginRoute() {
  const setup = useSetupStatus();
  const { status } = useAuth();
  if (setup.isPending || status === "loading") return <PageLoading label="Checking your session" />;
  if (setup.isError) return <SetupError error={setup.error} retry={() => void setup.refetch()} />;
  if (!setup.data.initialized) return <Navigate to="/setup" replace />;
  if (status === "unavailable") return <AuthUnavailable />;
  if (status === "authenticated") return <Navigate to="/dashboard" replace />;
  return <LoginPage setupStatus={setup.data} />;
}

function ProtectedRoute() {
  const setup = useSetupStatus();
  const { status } = useAuth();
  const location = useLocation();
  if (setup.isPending || status === "loading") return <PageLoading label="Opening your budget" />;
  if (setup.isError) return <SetupError error={setup.error} retry={() => void setup.refetch()} />;
  if (!setup.data.initialized) return <Navigate to="/setup" replace />;
  if (status === "unavailable") return <AuthUnavailable />;
  if (status !== "authenticated") return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <AppShell />;
}

function NotFoundPage() {
  return (
    <div className="page-container not-found">
      <span className="eyebrow">404</span>
      <h1>That page is not in your budget.</h1>
      <p>The link may be old, or the page may have moved.</p>
      <Navigate to="/dashboard" replace />
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />
      <Route path="/setup" element={<SetupRoute />} />
      <Route path="/login" element={<LoginRoute />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/accounts" element={<AccountsPage />} />
        <Route path="/plaid/oauth" element={<PlaidOAuthPage />} />
        <Route path="/transactions" element={<TransactionsPage />} />
        <Route path="/recurring" element={<RecurringPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
