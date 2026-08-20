import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ApiError, apiRequest } from "../api/client";
import type { AuthSession, InvitationDetails } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "../components/Brand";
import { ErrorState, LoadingState } from "../components/States";

const CHALLENGE_KEY = "budget-invite-challenge";
const DETAILS_KEY = "budget-invite-details";

function storedInvitation(): InvitationDetails | null {
  try {
    const raw = sessionStorage.getItem(DETAILS_KEY);
    const challenge = sessionStorage.getItem(CHALLENGE_KEY);
    if (!raw || !challenge) return null;
    const parsed = JSON.parse(raw) as Omit<InvitationDetails, "challenge_token">;
    return { ...parsed, challenge_token: challenge };
  } catch {
    return null;
  }
}

export function InvitePage() {
  const { token: routeToken } = useParams();
  const [params] = useSearchParams();
  const rawToken = routeToken ?? params.get("token") ?? "";
  const navigate = useNavigate();
  const { establishSession } = useAuth();
  const [invitation, setInvitation] = useState<InvitationDetails | null>(() => rawToken ? null : storedInvitation());
  const [checking, setChecking] = useState(Boolean(rawToken));
  const [exchangeError, setExchangeError] = useState<string | null>(null);
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!rawToken) return;
    let cancelled = false;
    setChecking(true);
    setExchangeError(null);
    void apiRequest<InvitationDetails>("/auth/invitations/exchange", {
      method: "POST",
      body: JSON.stringify({ token: rawToken }),
    }).then((details) => {
      if (cancelled) return;
      setInvitation(details);
      sessionStorage.setItem(CHALLENGE_KEY, details.challenge_token);
      sessionStorage.setItem(DETAILS_KEY, JSON.stringify({ label: details.label, invite_type: details.invite_type, budget_owner_username: details.budget_owner_username, expires_at: details.expires_at, google_enabled: details.google_enabled }));
      window.history.replaceState({}, "", "/join");
    }).catch((caught) => {
      if (!cancelled) setExchangeError(caught instanceof ApiError ? caught.message : "This invitation could not be opened.");
    }).finally(() => {
      if (!cancelled) setChecking(false);
    });
    return () => { cancelled = true; };
  }, [rawToken]);

  const expires = useMemo(() => invitation ? new Date(invitation.expires_at).toLocaleString() : null, [invitation]);

  const accept = async (event: FormEvent) => {
    event.preventDefault();
    if (!invitation) return;
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const session = await apiRequest<AuthSession>("/auth/invitations/accept", {
        method: "POST",
        body: JSON.stringify({ challenge_token: invitation.challenge_token, email, username, password }),
      });
      sessionStorage.removeItem(CHALLENGE_KEY);
      sessionStorage.removeItem(DETAILS_KEY);
      establishSession(session);
      navigate("/onboarding", { replace: true });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The invitation could not be accepted.");
    } finally {
      setBusy(false);
    }
  };

  const continueWithGoogle = () => {
    if (!invitation) return;
    const query = new URLSearchParams({ invite_challenge: invitation.challenge_token, return_to: "/onboarding" });
    window.location.assign(`/api/v1/auth/google/start?${query.toString()}`);
  };

  return (
    <main className="centered-page auth-flow-page join-page">
      <Brand linked={false} />
      <section className="auth-card auth-flow-card join-card">
        <span className="eyebrow">Private Budget link</span>
        <h1>Welcome to Budget</h1>
        <p className="join-lede">{invitation?.invite_type === "shared" ? `You've been invited to join ${invitation.budget_owner_username ?? "a family"}'s shared Budget. After account setup, you'll see the same household accounts, transactions, budgets, goals, subscriptions, and planning.` : "You've been invited to use Budget with your own private finances. Create your account, then we'll walk through first-time setup before you reach the dashboard."}</p>
        {checking && <LoadingState label="Opening your invitation" />}
        {exchangeError && <ErrorState title="Invitation unavailable" message="This invitation is invalid, expired, revoked, or has already been used." />}
        {!checking && !exchangeError && !invitation && <ErrorState title="Invitation link missing" message="Ask the Budget administrator for a new invite link." />}
        {invitation && (
          <>
            <div className="join-invite-meta"><strong>{invitation.label || "Budget invitation"}</strong><small>{invitation.invite_type === "shared" ? `Shared Budget · ${invitation.budget_owner_username ?? "Family"}` : "Independent Budget"} · one-time link · expires {expires}</small></div>
            {invitation.google_enabled && (
              <>
                <button className="button secondary wide google-signin" type="button" onClick={continueWithGoogle}><span className="google-g" aria-hidden="true">G</span> Continue with Google</button>
                <div className="auth-divider"><span>or create an account</span></div>
              </>
            )}
            {error && <div className="inline-alert" role="alert">{error}</div>}
            <form className="form-stack" onSubmit={accept}>
              <label>Email<input required type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} /></label>
              <label>Username<input required minLength={3} maxLength={80} pattern="[A-Za-z0-9._-]+" autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label>
              <label>Password<input required minLength={12} maxLength={128} type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
              <label>Confirm password<input required minLength={12} maxLength={128} type="password" autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>
              <button className="button primary wide" type="submit" disabled={busy}>{busy ? "Creating account…" : "Create Budget account"}</button>
            </form>
          </>
        )}
        <Link to="/login">Already have an account? Sign in</Link>
      </section>
    </main>
  );
}
