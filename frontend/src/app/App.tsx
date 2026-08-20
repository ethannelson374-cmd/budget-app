import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ApiError } from "../api/client";
import { useSetupStatus } from "../api/queries";
import { useAuth } from "../auth/AuthContext";
import { AppShell } from "../components/AppShell";
import { Brand } from "../components/Brand";
import { ErrorState, PageLoading } from "../components/States";
import { LoginPage } from "../pages/LoginPage";
import { InvitePage } from "../pages/InvitePage";
import { ForgotPasswordPage } from "../pages/ForgotPasswordPage";
import { ResetPasswordPage } from "../pages/ResetPasswordPage";
import { GoogleAuthCompletePage } from "../pages/GoogleAuthCompletePage";
import { SetupPage } from "../pages/SetupPage";

const AccountsPage = lazy(() => import("../pages/AccountsPage").then((module) => ({ default: module.AccountsPage })));
const AdvisorWorkspacePage = lazy(() => import("../pages/AdvisorWorkspacePage").then((module) => ({ default: module.AdvisorWorkspacePage })));
const AnalyticsPage = lazy(() => import("../pages/AnalyticsPage").then((module) => ({ default: module.AnalyticsPage })));
const DashboardPage = lazy(() => import("../pages/DashboardPage").then((module) => ({ default: module.DashboardPage })));
const OnboardingPage = lazy(() => import("../pages/OnboardingPage").then((module) => ({ default: module.OnboardingPage })));
const NotificationsPage = lazy(() => import("../pages/NotificationsPage").then((module) => ({ default: module.NotificationsPage })));
const PlaidOAuthPage = lazy(() => import("../pages/PlaidOAuthPage").then((module) => ({ default: module.PlaidOAuthPage })));
const PlanPage = lazy(() => import("../pages/PlanPage").then((module) => ({ default: module.PlanPage })));
const RecurringPage = lazy(() => import("../pages/RecurringPage").then((module) => ({ default: module.RecurringPage })));
const SettingsPage = lazy(() => import("../pages/SettingsPage").then((module) => ({ default: module.SettingsPage })));
const TransactionsPage = lazy(() => import("../pages/TransactionsPage").then((module) => ({ default: module.TransactionsPage })));

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
  const { status, user } = useAuth();
  if (setup.isPending || status === "loading") return <PageLoading />;
  if (setup.isError) return <SetupError error={setup.error} retry={() => void setup.refetch()} />;
  if (!setup.data.initialized) return <Navigate to="/setup" replace />;
  if (status === "unavailable") return <AuthUnavailable />;
  return <Navigate to={status === "authenticated" ? (user?.settings.onboarding_complete === false ? "/onboarding" : "/dashboard") : "/login"} replace />;
}

function SetupRoute() {
  const setup = useSetupStatus();
  const { status, user } = useAuth();
  if (setup.isPending || status === "loading") return <PageLoading label="Checking installation" />;
  if (setup.isError) return <SetupError error={setup.error} retry={() => void setup.refetch()} />;
  if (setup.data.initialized) return <Navigate to={status === "authenticated" ? (user?.settings.onboarding_complete === false ? "/onboarding" : "/dashboard") : "/login"} replace />;
  return <SetupPage status={setup.data} />;
}

function LoginRoute() {
  const setup = useSetupStatus();
  const { status, user } = useAuth();
  if (setup.isPending || status === "loading") return <PageLoading label="Checking your session" />;
  if (setup.isError) return <SetupError error={setup.error} retry={() => void setup.refetch()} />;
  if (!setup.data.initialized) return <Navigate to="/setup" replace />;
  if (status === "unavailable") return <AuthUnavailable />;
  if (status === "authenticated") return <Navigate to={user?.settings.onboarding_complete === false ? "/onboarding" : "/dashboard"} replace />;
  return <LoginPage setupStatus={setup.data} />;
}

function ProtectedRoute() {
  const setup = useSetupStatus();
  const { status, user } = useAuth();
  const location = useLocation();
  if (setup.isPending || status === "loading") return <PageLoading label="Opening your budget" />;
  if (setup.isError) return <SetupError error={setup.error} retry={() => void setup.refetch()} />;
  if (!setup.data.initialized) return <Navigate to="/setup" replace />;
  if (status === "unavailable") return <AuthUnavailable />;
  if (status !== "authenticated") return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  if (user?.settings.onboarding_complete === false) return <Navigate to="/onboarding" replace />;
  return <AppShell />;
}

function PlaidOAuthRoute() {
  const setup = useSetupStatus();
  const { status } = useAuth();
  if (setup.isPending || status === "loading") return <PageLoading label="Finishing your bank connection" />;
  if (setup.isError) return <SetupError error={setup.error} retry={() => void setup.refetch()} />;
  if (!setup.data.initialized) return <Navigate to="/setup" replace />;
  if (status === "unavailable") return <AuthUnavailable />;
  if (status !== "authenticated") return <Navigate to="/login" replace />;
  return <LazyPage><PlaidOAuthPage /></LazyPage>;
}

function OnboardingRoute() {
  const setup = useSetupStatus();
  const { status, user } = useAuth();
  if (setup.isPending || status === "loading") return <PageLoading label="Opening first-time setup" />;
  if (setup.isError) return <SetupError error={setup.error} retry={() => void setup.refetch()} />;
  if (!setup.data.initialized) return <Navigate to="/setup" replace />;
  if (status === "unavailable") return <AuthUnavailable />;
  if (status !== "authenticated") return <Navigate to="/login" replace />;
  if (user?.settings.onboarding_complete !== false) return <Navigate to="/dashboard" replace />;
  return <LazyPage><OnboardingPage /></LazyPage>;
}

function LazyPage({ children }: { children: ReactNode }) {
  return <Suspense fallback={<PageLoading label="Loading this workspace" />}>{children}</Suspense>;
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
      <Route path="/join/:token" element={<InvitePage />} />
      <Route path="/join" element={<InvitePage />} />
      <Route path="/invite" element={<InvitePage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/auth/google/complete" element={<GoogleAuthCompletePage />} />
      <Route path="/onboarding" element={<OnboardingRoute />} />
      <Route path="/plaid/oauth" element={<PlaidOAuthRoute />} />
      <Route element={<ProtectedRoute />}>
        <Route path="/dashboard" element={<LazyPage><DashboardPage /></LazyPage>} />
        <Route path="/accounts" element={<LazyPage><AccountsPage /></LazyPage>} />
        <Route path="/transactions" element={<LazyPage><TransactionsPage /></LazyPage>} />
        <Route path="/budget" element={<Navigate to="/plan?tab=budget" replace />} />
        <Route path="/plan" element={<LazyPage><PlanPage /></LazyPage>} />
        <Route path="/calendar" element={<LazyPage><RecurringPage /></LazyPage>} />
        <Route path="/recurring" element={<LazyPage><RecurringPage /></LazyPage>} />
        <Route path="/insights" element={<Navigate to="/analytics?tab=insights" replace />} />
        <Route path="/trends" element={<Navigate to="/analytics?tab=trends" replace />} />
        <Route path="/analytics" element={<LazyPage><AnalyticsPage /></LazyPage>} />
        <Route path="/reports" element={<Navigate to="/advisor?tab=reports" replace />} />
        <Route path="/advisor" element={<LazyPage><AdvisorWorkspacePage /></LazyPage>} />
        <Route path="/settings" element={<LazyPage><SettingsPage /></LazyPage>} />
        <Route path="/notifications" element={<LazyPage><NotificationsPage /></LazyPage>} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
