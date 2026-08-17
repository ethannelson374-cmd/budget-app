import { useMemo, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ApiError } from "../api/client";
import type { SetupStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "../components/Brand";
import { Icon } from "../components/Icon";

interface LocationState {
  from?: string;
  setupComplete?: boolean;
}

const googleErrors: Record<string, string> = {
  google_cancelled: "Google sign-in was cancelled.",
  google_provider_error: "Google sign-in could not be completed. Try again.",
  google_link_required: "A Budget account already uses that email. Sign in with your password, then connect Google from Settings.",
  invitation_required: "Budget is private. Ask the account owner for a fresh invite link.",
  google_state_invalid: "That Google sign-in request expired. Start again.",
  google_nonce_invalid: "Budget could not verify that Google sign-in response. Start again.",
};

export function LoginPage({ setupStatus }: { setupStatus: SetupStatus }) {
  const { login, verifyTwoFactor, demoLogin } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const state = (location.state ?? {}) as LocationState;
  const returnTo = state.from?.startsWith("/") && !state.from.startsWith("//") ? state.from : "/dashboard";
  const [identity, setIdentity] = useState("");
  const [password, setPassword] = useState("");
  const [twoFactorCode, setTwoFactorCode] = useState("");
  const [challengeToken, setChallengeToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demoBusy, setDemoBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const authError = useMemo(() => {
    const code = new URLSearchParams(location.search).get("auth_error");
    return code ? googleErrors[code] ?? "Sign-in could not be completed." : null;
  }, [location.search]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (challengeToken) {
        await verifyTwoFactor(challengeToken, twoFactorCode);
        setTwoFactorCode("");
        navigate(returnTo, { replace: true });
        return;
      }
      const outcome = await login(identity, password);
      setPassword("");
      if (outcome.twoFactorRequired && outcome.challengeToken) {
        setChallengeToken(outcome.challengeToken);
        return;
      }
      navigate(returnTo, { replace: true });
    } catch (caught) {
      setPassword("");
      setTwoFactorCode("");
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

  const googleSignIn = () => {
    const params = new URLSearchParams({ return_to: returnTo });
    window.location.assign(`/api/v1/auth/google/start?${params.toString()}`);
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
          <div><span className="eyebrow">Welcome back</span><h2 id="login-heading">Sign in to Budget</h2><p>{challengeToken ? "Enter the code from your authenticator app or a recovery code." : "Use Google, your username, or your email address."}</p></div>
          {state.setupComplete && <div className="inline-alert success" role="status">Setup is complete. Sign in to continue.</div>}
          {authError && <div className="inline-alert" role="alert">{authError}</div>}
          {error && <div className="inline-alert" role="alert"><span>{error.retryAfter ? `Too many attempts. Try again in ${error.retryAfter} seconds.` : error.message}</span>{error.requestId && <small>Request ID: {error.requestId}</small>}</div>}

          {!challengeToken && setupStatus.google_auth_enabled && (
            <>
              <button className="button secondary wide google-signin" type="button" disabled={busy || demoBusy} onClick={googleSignIn}>
                <span className="google-g" aria-hidden="true">G</span> Continue with Google
              </button>
              <div className="auth-divider"><span>or</span></div>
            </>
          )}

          <form className="form-stack" onSubmit={submit}>
            {!challengeToken ? (
              <>
                <label>Username or email<input required autoComplete="username" value={identity} onChange={(event) => setIdentity(event.target.value)} /></label>
                <label>Password<input required type="password" maxLength={128} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
                <div className="auth-form-links"><Link to="/forgot-password">Forgot password?</Link></div>
              </>
            ) : (
              <>
                <label>Verification code<input required inputMode="numeric" autoComplete="one-time-code" maxLength={32} value={twoFactorCode} onChange={(event) => setTwoFactorCode(event.target.value)} /></label>
                <button className="button ghost" type="button" onClick={() => { setChallengeToken(null); setTwoFactorCode(""); }}>Use a different sign-in method</button>
              </>
            )}
            <button className="button primary wide" type="submit" disabled={busy || demoBusy}>{busy ? "Signing in…" : <>{challengeToken ? "Verify and sign in" : "Sign in"} <Icon name="arrow-right" /></>}</button>
          </form>
          {!challengeToken && setupStatus.invite_only && <small className="auth-private-note">Budget is private. New family members need a one-time invite link from an administrator.</small>}
          {!challengeToken && setupStatus.demo_mode && <div className="demo-login"><span>or explore without an account</span><button className="button secondary wide" type="button" disabled={busy || demoBusy} onClick={() => void enterDemo()}>{demoBusy ? "Opening demo…" : "Explore the demo"}</button><small>Demo data resets to a sample household.</small></div>}
        </section>
      </div>
    </main>
  );
}
