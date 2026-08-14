import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, apiRequest } from "../api/client";
import { Brand } from "../components/Brand";

export function ForgotPasswordPage() {
  const [identity, setIdentity] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiRequest<{ ok: boolean }>("/auth/password/forgot", {
        method: "POST",
        body: JSON.stringify({ identity }),
      });
      setSent(true);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The request could not be completed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="centered-page auth-flow-page">
      <Brand linked={false} />
      <section className="auth-card auth-flow-card">
        <span className="eyebrow">Account recovery</span>
        <h1>Reset your password</h1>
        {sent ? (
          <div className="inline-alert success" role="status">If that account exists and email delivery is configured, a reset link is on the way.</div>
        ) : (
          <>
            <p>Enter your username or email. Budget always returns the same response so account membership stays private.</p>
            {error && <div className="inline-alert" role="alert">{error}</div>}
            <form className="form-stack" onSubmit={submit}>
              <label>Username or email<input required autoComplete="username" value={identity} onChange={(event) => setIdentity(event.target.value)} /></label>
              <button className="button primary wide" type="submit" disabled={busy}>{busy ? "Sending…" : "Send reset link"}</button>
            </form>
          </>
        )}
        <Link to="/login">Back to sign in</Link>
      </section>
    </main>
  );
}
