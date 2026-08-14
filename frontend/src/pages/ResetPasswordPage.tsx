import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, apiRequest } from "../api/client";
import type { PasswordResetStatus } from "../api/types";
import { Brand } from "../components/Brand";
import { ErrorState, LoadingState } from "../components/States";

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const status = useQuery({
    queryKey: ["password-reset", token],
    queryFn: () => apiRequest<PasswordResetStatus>(`/auth/password/reset?token=${encodeURIComponent(token)}`),
    enabled: Boolean(token),
    retry: false,
  });
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
      await apiRequest<{ ok: boolean }>("/auth/password/reset", {
        method: "POST",
        body: JSON.stringify({ token, password }),
      });
      navigate("/login?password_reset=success", { replace: true });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The password could not be reset.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="centered-page auth-flow-page">
      <Brand linked={false} />
      <section className="auth-card auth-flow-card">
        <span className="eyebrow">Account recovery</span>
        <h1>Choose a new password</h1>
        {!token && <ErrorState title="Reset link missing" message="Request a new password reset link." />}
        {status.isPending && <LoadingState label="Checking reset link" />}
        {status.data && !status.data.valid && <ErrorState title="Reset link expired" message="This password reset link is invalid, expired, or has already been used." />}
        {status.data?.valid && (
          <>
            <p>Resetting the password for <strong>{status.data.email}</strong> will sign out every existing Budget session.</p>
            {error && <div className="inline-alert" role="alert">{error}</div>}
            <form className="form-stack" onSubmit={submit}>
              <label>New password<input required type="password" minLength={12} maxLength={128} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
              <label>Confirm new password<input required type="password" minLength={12} maxLength={128} autoComplete="new-password" value={confirm} onChange={(event) => setConfirm(event.target.value)} /></label>
              <button className="button primary wide" type="submit" disabled={busy}>{busy ? "Resetting…" : "Reset password"}</button>
            </form>
          </>
        )}
        {status.isError && <ErrorState title="Reset unavailable" message="Budget could not verify this reset link." />}
        <Link to="/login">Back to sign in</Link>
      </section>
    </main>
  );
}
