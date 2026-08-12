import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import type { SetupStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "../components/Brand";
import { Icon } from "../components/Icon";

interface LocationState {
  from?: string;
  setupComplete?: boolean;
}

export function LoginPage({ setupStatus }: { setupStatus: SetupStatus }) {
  const { login, demoLogin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const state = (location.state ?? {}) as LocationState;
  const returnTo = state.from?.startsWith("/") && !state.from.startsWith("//") ? state.from : "/dashboard";
  const [identity, setIdentity] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(identity, password);
      setPassword("");
      navigate(returnTo, { replace: true });
    } catch (caught) {
      setPassword("");
      setError(caught instanceof ApiError ? caught : new ApiError("The server could not be reached.", { status: 0 }));
    } finally {
      setBusy(false);
    }
  };

  const enterDemo = async () => {
    setDemoBusy(true);
    setError(null);
    try {
      await demoLogin();
      navigate("/dashboard", { replace: true });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError("The demo could not be opened.", { status: 0 }));
    } finally {
      setDemoBusy(false);
    }
  };

  return (
    <main className="auth-page login-page">
      <div className="login-layout">
        <section className="login-intro" aria-labelledby="welcome-heading">
          <Brand linked={false} />
          <div><span className="eyebrow">A calmer way to see your money</span><h1 id="welcome-heading">Clarity for every dollar.</h1><p>Understand what came in, what went out, and where you stand—all in one private workspace.</p></div>
          <div className="trust-note"><span aria-hidden="true">✓</span><p><strong>Your data stays yours.</strong><br />Authenticated sessions and same-origin requests protect every view.</p></div>
        </section>
        <section className="auth-card login-card" aria-labelledby="login-heading">
          <div><span className="eyebrow">Welcome back</span><h2 id="login-heading">Sign in to Budget</h2><p>Use your username or email address.</p></div>
          {state.setupComplete && <div className="inline-alert success" role="status">Setup is complete. Sign in to continue.</div>}
          {error && <div className="inline-alert" role="alert"><span>{error.retryAfter ? `Too many attempts. Try again in ${error.retryAfter} seconds.` : error.message}</span>{error.requestId && <small>Request ID: {error.requestId}</small>}</div>}
          <form className="form-stack" onSubmit={submit}>
            <label>Username or email<input required autoComplete="username" value={identity} onChange={(event) => setIdentity(event.target.value)} /></label>
            <label>Password<input required type="password" maxLength={128} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
            <button className="button primary wide" type="submit" disabled={busy || demoBusy}>{busy ? "Signing in…" : <>Sign in <Icon name="arrow-right" /></>}</button>
          </form>
          {setupStatus.demo_mode && <div className="demo-login"><span>or explore without an account</span><button className="button secondary wide" type="button" disabled={busy || demoBusy} onClick={() => void enterDemo()}>{demoBusy ? "Opening demo…" : "Explore the demo"}</button><small>Demo data resets to a sample household.</small></div>}
        </section>
      </div>
    </main>
  );
}
