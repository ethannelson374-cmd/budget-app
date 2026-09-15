import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, apiRequest } from "../api/client";
import type { AuthSession } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "../components/Brand";

export function SignupPage({ googleEnabled }: { googleEnabled: boolean }) {
  const navigate = useNavigate();
  const { establishSession } = useAuth();
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const session = await apiRequest<AuthSession>("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, username, password }),
      });
      setPassword("");
      setConfirm("");
      establishSession(session);
      navigate("/onboarding", { replace: true });
    } catch (caught) {
      setPassword("");
      setConfirm("");
      setError(caught instanceof ApiError ? caught.message : "Account creation could not be completed.");
    } finally {
      setBusy(false);
    }
  };

  const continueWithGoogle = () => {
    window.location.assign("/api/v1/auth/google/start?return_to=/onboarding");
  };

  return (
    <main className="centered-page auth-flow-page signup-page">
      <Brand linked={false} />
      <section className="auth-card auth-flow-card signup-card" aria-labelledby="signup-title">
        <span className="eyebrow">Start your Budget</span>
        <h1 id="signup-title">Create your account</h1>
        <p>Set up your private financial workspace, then we’ll guide you through the first steps.</p>
        {googleEnabled && <><button className="button secondary wide google-signin" type="button" disabled={busy} onClick={continueWithGoogle}><span className="google-g" aria-hidden="true">G</span> Continue with Google</button><div className="auth-divider"><span>or create an account</span></div></>}
        {error && <div className="inline-alert" role="alert">{error}</div>}
        <form className="form-stack" onSubmit={submit}>
          <label>Email<input required type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          <label>Username<input required minLength={3} maxLength={80} pattern="[A-Za-z0-9._-]+" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label>
          <label>Password<input required minLength={12} maxLength={128} type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <label>Confirm password<input required minLength={12} maxLength={128} type="password" autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>
          <button className="button primary wide" type="submit" disabled={busy}>{busy ? "Creating account…" : "Create Budget account"}</button>
        </form>
        <Link to="/login">Already have an account? Sign in</Link>
      </section>
    </main>
  );
}
