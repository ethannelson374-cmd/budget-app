import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, apiRequest } from "../api/client";
import type { AuthSession, InvitationDetails } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "../components/Brand";
import { ErrorState, LoadingState } from "../components/States";

export function InvitePage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const { establishSession } = useAuth();
  const invitation = useQuery({
    queryKey: ["invitation", token],
    queryFn: () => apiRequest<InvitationDetails>(`/auth/invitations/${encodeURIComponent(token)}`),
    enabled: Boolean(token),
    retry: false,
  });
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const accept = async (event: FormEvent) => {
    event.preventDefault();
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const session = await apiRequest<AuthSession>("/auth/invitations/accept", {
        method: "POST",
        body: JSON.stringify({ token, username, password }),
      });
      establishSession(session);
      navigate("/dashboard", { replace: true });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The invitation could not be accepted.");
    } finally {
      setBusy(false);
    }
  };

  const continueWithGoogle = () => {
    const query = new URLSearchParams({ invite: token, return_to: "/dashboard" });
    window.location.assign(`/api/v1/auth/google/start?${query.toString()}`);
  };

  return (
    <main className="centered-page auth-flow-page">
      <Brand linked={false} />
      <section className="auth-card auth-flow-card">
        <span className="eyebrow">Private invitation</span>
        <h1>Join Budget</h1>
        {!token && <ErrorState title="Invitation link missing" message="Ask the Budget administrator for a new invitation." />}
        {invitation.isPending && <LoadingState label="Checking invitation" />}
        {invitation.isError && <ErrorState title="Invitation unavailable" message="This invitation is invalid, expired, or has already been used." />}
        {invitation.data && (
          <>
            <p>You were invited as <strong>{invitation.data.email}</strong>. Your finances stay isolated from every other Budget user.</p>
            {invitation.data.google_enabled && (
              <>
                <button className="button secondary wide google-signin" type="button" onClick={continueWithGoogle}><span className="google-g" aria-hidden="true">G</span> Continue with Google</button>
                <div className="auth-divider"><span>or create a password</span></div>
              </>
            )}
            {error && <div className="inline-alert" role="alert">{error}</div>}
            <form className="form-stack" onSubmit={accept}>
              <label>Username<input required minLength={3} maxLength={80} pattern="[A-Za-z0-9._-]+" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label>
              <label>Password<input required minLength={12} maxLength={128} type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
              <label>Confirm password<input required minLength={12} maxLength={128} type="password" autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>
              <button className="button primary wide" type="submit" disabled={busy}>{busy ? "Creating account…" : "Create Budget account"}</button>
            </form>
          </>
        )}
        <Link to="/login">Back to sign in</Link>
      </section>
    </main>
  );
}
