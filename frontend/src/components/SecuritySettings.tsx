import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type {
  AdminUsersResponse,
  AuthSessionsResponse,
  FamilyStatus,
  ResetDelivery,
  SecurityStatus,
  TotpConfirmation,
  TotpSetup,
  UserInvitation,
  UserInvitationsResponse,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ErrorState, LoadingState } from "./States";

function sessionLabel(userAgent: string | null): string {
  if (!userAgent) return "Unknown browser";
  const browser = userAgent.includes("Edg/") ? "Edge" : userAgent.includes("Chrome/") ? "Chrome" : userAgent.includes("Firefox/") ? "Firefox" : userAgent.includes("Safari/") ? "Safari" : "Browser";
  const device = userAgent.includes("Windows") ? "Windows" : userAgent.includes("iPhone") ? "iPhone" : userAgent.includes("iPad") ? "iPad" : userAgent.includes("Android") ? "Android" : userAgent.includes("Macintosh") ? "macOS" : userAgent.includes("Linux") ? "Linux" : "device";
  return `${browser} · ${device}`;
}

function dateTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Never";
}

export function SecuritySettings() {
  const { user, refresh } = useAuth();
  const queryClient = useQueryClient();
  const security = useQuery({ queryKey: queryKeys.securityStatus, queryFn: () => apiRequest<SecurityStatus>("/auth/security") });
  const sessions = useQuery({ queryKey: queryKeys.authSessions, queryFn: () => apiRequest<AuthSessionsResponse>("/auth/sessions") });
  const invitations = useQuery({ queryKey: queryKeys.userInvitations, queryFn: () => apiRequest<UserInvitationsResponse>("/auth/invitations") });
  const family = useQuery({ queryKey: queryKeys.familyStatus, queryFn: () => apiRequest<FamilyStatus>("/auth/family") });
  const adminUsers = useQuery({ queryKey: queryKeys.adminUsers, queryFn: () => apiRequest<AdminUsersResponse>("/auth/admin/users"), enabled: Boolean(user?.is_admin) });

  if (security.isPending || sessions.isPending) return <section className="panel security-panel"><LoadingState label="Loading account security" /></section>;
  if (security.isError || sessions.isError || !security.data || !sessions.data) return <section className="panel security-panel"><ErrorState title="Security settings unavailable" message="Budget could not load your sign-in settings." onRetry={() => { void security.refetch(); void sessions.refetch(); }} /></section>;

  return (
    <section className="settings-security" aria-labelledby="security-settings-heading">
      <div className="settings-section-heading"><div><span className="eyebrow">Identity & security</span><h2 id="security-settings-heading">Sign-in and account access</h2><p>Budget uses private invite links. Manage sign-in methods, sessions, and family access here.</p></div></div>
      <div className="security-grid">
        <SignInMethods status={security.data} refreshSecurity={() => void security.refetch()} />
        <TwoFactorCard status={security.data} refreshSecurity={() => void security.refetch()} />
        <SessionCard sessions={sessions.data} refreshSessions={() => void sessions.refetch()} />
        <FamilyAccessCard invitations={invitations.data?.invitations ?? []} family={family.data ?? null} users={adminUsers.data?.users ?? []} isAdmin={Boolean(user?.is_admin)} loading={invitations.isPending || family.isPending || (Boolean(user?.is_admin) && adminUsers.isPending)} refresh={() => { void invitations.refetch(); void family.refetch(); if (user?.is_admin) void adminUsers.refetch(); }} />
        <DeleteAccountCard hasPassword={security.data.has_password} onDeleted={async () => { queryClient.clear(); await refresh(); window.location.assign("/"); }} />
      </div>
    </section>
  );
}

function SignInMethods({ status, refreshSecurity }: { status: SecurityStatus; refreshSecurity: () => void }) {
  const [message, setMessage] = useState<string | null>(null);
  const unlink = useMutation({
    mutationFn: () => apiRequest<{ ok: boolean }>("/auth/google", { method: "DELETE" }),
    onSuccess: () => { setMessage("Google sign-in disconnected."); refreshSecurity(); },
  });
  const googleLink = () => window.location.assign("/api/v1/auth/google/link/start?return_to=/settings");
  return (
    <article className="panel security-card">
      <div className="security-card-heading"><div><span className="eyebrow">Sign-in methods</span><h3>Account identity</h3></div><span className={`status-pill ${status.email_verified ? "success" : ""}`}>{status.email_verified ? "Email verified" : "Email unverified"}</span></div>
      <div className="security-method"><div><strong>Password</strong><small>{status.has_password ? "Configured" : "Not configured"}</small></div><span>{status.has_password ? "✓" : "—"}</span></div>
      <div className="security-method"><div><strong>Google</strong><small>{status.google_connected ? "Connected" : status.google_enabled ? "Available" : "Not configured by administrator"}</small></div>{status.google_enabled && (status.google_connected ? <button className="button secondary" type="button" disabled={unlink.isPending} onClick={() => unlink.mutate()}>Disconnect</button> : <button className="button secondary" type="button" onClick={googleLink}>Connect Google</button>)}</div>
      {unlink.error instanceof ApiError && <div className="inline-alert" role="alert">{unlink.error.message}</div>}
      {message && <div className="inline-alert success" role="status">{message}</div>}
    </article>
  );
}

function TwoFactorCard({ status, refreshSecurity }: { status: SecurityStatus; refreshSecurity: () => void }) {
  const [setup, setSetup] = useState<TotpSetup | null>(null);
  const [code, setCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const begin = useMutation({
    mutationFn: () => apiRequest<TotpSetup>("/auth/totp/setup", { method: "POST" }),
    onSuccess: (data) => { setSetup(data); setRecoveryCodes([]); setError(null); },
  });
  const confirm = useMutation({
    mutationFn: () => apiRequest<TotpConfirmation>("/auth/totp/confirm", { method: "POST", body: JSON.stringify({ code }) }),
    onSuccess: (data) => { setRecoveryCodes(data.recovery_codes); setSetup(null); setCode(""); refreshSecurity(); },
    onError: (caught) => setError(caught instanceof ApiError ? caught.message : "The code could not be verified."),
  });
  const disable = useMutation({
    mutationFn: () => apiRequest<{ ok: boolean }>("/auth/totp", { method: "DELETE", body: JSON.stringify({ code }) }),
    onSuccess: () => { setCode(""); setRecoveryCodes([]); refreshSecurity(); },
    onError: (caught) => setError(caught instanceof ApiError ? caught.message : "Two-factor authentication could not be disabled."),
  });
  return (
    <article className="panel security-card">
      <div className="security-card-heading"><div><span className="eyebrow">Two-factor authentication</span><h3>Authenticator app</h3></div><span className={`status-pill ${status.two_factor_enabled ? "success" : ""}`}>{status.two_factor_enabled ? "Enabled" : "Optional"}</span></div>
      {!status.two_factor_enabled && !setup && <><p>Add a second check to password sign-in. Google sign-in continues to use Google's own account protections.</p><button className="button secondary" type="button" disabled={begin.isPending} onClick={() => begin.mutate()}>{begin.isPending ? "Preparing…" : "Set up authenticator"}</button></>}
      {setup && <div className="totp-setup"><p>In your authenticator app, choose <strong>Enter setup key</strong> and use:</p><code className="secret-code">{setup.secret}</code><small>Account: Budget · your verified email · time-based 6-digit code</small><label>Verification code<input inputMode="numeric" autoComplete="one-time-code" maxLength={32} value={code} onChange={(event) => setCode(event.target.value)} /></label><button className="button primary" type="button" disabled={!code || confirm.isPending} onClick={() => confirm.mutate()}>{confirm.isPending ? "Verifying…" : "Enable 2FA"}</button></div>}
      {status.two_factor_enabled && <div className="totp-disable"><p>Use a current authenticator code or an unused recovery code to disable 2FA.</p><label>Verification or recovery code<input maxLength={32} value={code} onChange={(event) => setCode(event.target.value)} /></label><button className="button secondary" type="button" disabled={!code || disable.isPending} onClick={() => disable.mutate()}>{disable.isPending ? "Disabling…" : "Disable 2FA"}</button></div>}
      {recoveryCodes.length > 0 && <div className="recovery-codes"><strong>Save these recovery codes now</strong><p>Each code works once. Budget will not show this list again.</p><div>{recoveryCodes.map((item) => <code key={item}>{item}</code>)}</div></div>}
      {(error || begin.error instanceof ApiError) && <div className="inline-alert" role="alert">{error ?? (begin.error as ApiError).message}</div>}
    </article>
  );
}

function SessionCard({ sessions, refreshSessions }: { sessions: AuthSessionsResponse; refreshSessions: () => void }) {
  const revoke = useMutation({
    mutationFn: (id: number) => apiRequest<{ ok: boolean }>(`/auth/sessions/${id}`, { method: "DELETE" }),
    onSuccess: refreshSessions,
  });
  const revokeOthers = useMutation({
    mutationFn: () => apiRequest<{ ok: boolean }>("/auth/sessions/revoke-others", { method: "POST" }),
    onSuccess: refreshSessions,
  });
  return (
    <article className="panel security-card security-sessions">
      <div className="security-card-heading"><div><span className="eyebrow">Sessions</span><h3>Signed-in devices</h3></div>{sessions.sessions.length > 1 && <button className="button ghost" type="button" disabled={revokeOthers.isPending} onClick={() => revokeOthers.mutate()}>Sign out others</button>}</div>
      <div className="session-list">{sessions.sessions.map((session) => <div className="session-row" key={session.id}><div><strong>{sessionLabel(session.user_agent)}</strong><small>{session.current ? "Current session" : `Last active ${dateTime(session.last_seen_at)}`}</small><small>Expires {dateTime(session.absolute_expires_at)}</small></div>{session.current ? <span className="status-pill success">Current</span> : <button className="button secondary" type="button" disabled={revoke.isPending} onClick={() => revoke.mutate(session.id)}>Sign out</button>}</div>)}</div>
    </article>
  );
}

function FamilyAccessCard({ invitations, family, users, isAdmin, loading, refresh }: { invitations: UserInvitation[]; family: FamilyStatus | null; users: AdminUsersResponse["users"]; isAdmin: boolean; loading: boolean; refresh: () => void }) {
  const [label, setLabel] = useState("");
  const [inviteType, setInviteType] = useState<"shared" | "independent">("shared");
  const [manualLink, setManualLink] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const invite = useMutation({
    mutationFn: () => apiRequest<UserInvitation>("/auth/invitations", { method: "POST", body: JSON.stringify({ label: label.trim() || null, invite_type: inviteType }) }),
    onSuccess: (data) => {
      setLabel("");
      setManualLink(data.invite_url ?? null);
      setMessage(data.invite_type === "shared" ? "Shared-Budget invite created. This person will join your current financial space after setup." : "App invite created. This person will get their own private Budget after setup.");
      refresh();
    },
  });
  const revoke = useMutation({ mutationFn: (id: number) => apiRequest<{ ok: boolean }>(`/auth/invitations/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const removeMember = useMutation({ mutationFn: (id: number) => apiRequest<FamilyStatus>(`/auth/family/members/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const leaveBudget = useMutation({ mutationFn: () => apiRequest<FamilyStatus>("/auth/family/leave", { method: "POST" }), onSuccess: () => { setMessage("You left the shared Budget. Your account now has a new private financial space."); refresh(); } });
  const reset = useMutation({
    mutationFn: (id: number) => apiRequest<ResetDelivery>(`/auth/admin/users/${id}/password-reset`, { method: "POST" }),
    onSuccess: (data) => { setManualLink(data.reset_url ?? null); setMessage(data.delivery === "email" ? "Password reset email sent." : "Password reset link created. Copy it below."); },
  });
  const submit = (event: FormEvent) => { event.preventDefault(); setManualLink(null); setMessage(null); invite.mutate(); };
  const householdMembers = family?.members ?? [];
  return (
    <article className="panel security-card family-access-card">
      <div className="security-card-heading"><div><span className="eyebrow">Family access</span><h3>Private invite links</h3></div><span className={`status-pill ${family?.shared ? "success" : ""}`}>{family?.shared ? "Shared Budget" : "Personal Budget"}</span></div>
      <p>Invite someone into <strong>{family?.budget_owner_username ?? "your"}'s Budget</strong>, or simply give them access to the app with finances that stay completely separate.</p>
      <form className="invite-form phase6-invite-form" onSubmit={submit}>
        <fieldset className="invite-type-picker">
          <legend>Invitation type</legend>
          <label className={inviteType === "shared" ? "selected" : ""}><input type="radio" name="invite-type" value="shared" checked={inviteType === "shared"} onChange={() => setInviteType("shared")} /><span><strong>Join my Budget</strong><small>Share accounts, transactions, budgets, goals, recurring activity, subscriptions, reports, and planning.</small></span></label>
          <label className={inviteType === "independent" ? "selected" : ""}><input type="radio" name="invite-type" value="independent" checked={inviteType === "independent"} onChange={() => setInviteType("independent")} /><span><strong>Use Budget independently</strong><small>Give them access to the app, but create a separate private financial space.</small></span></label>
        </fieldset>
        <label>Label <small>Optional — only Budget users see this</small><input maxLength={120} value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Partner, Mom, brother…" /></label>
        <button className="button primary" type="submit" disabled={invite.isPending}>{invite.isPending ? "Creating…" : "Create invite link"}</button>
      </form>
      {invite.error instanceof ApiError && <div className="inline-alert" role="alert">{invite.error.message}</div>}
      {message && <div className="inline-alert success" role="status">{message}</div>}
      {manualLink && <div className="manual-link"><input readOnly value={manualLink} aria-label="Private account link" /><button className="button secondary" type="button" onClick={() => void navigator.clipboard?.writeText(manualLink)}>Copy</button></div>}
      {loading ? <LoadingState label="Loading family access" /> : <>
        <div className="family-users"><strong>People in this Budget</strong>{householdMembers.map((member) => <div className="family-user" key={member.id}><div><b>{member.username}{member.is_current ? " · You" : ""}</b><small>{member.email} · {member.role === "owner" ? "Budget owner" : "Full member"}</small></div><div className="family-member-actions"><span className={`status-pill ${member.role === "owner" ? "success" : ""}`}>{member.role}</span>{family?.role === "owner" && member.role === "member" && <button className="button ghost" type="button" disabled={removeMember.isPending} onClick={() => { if (window.confirm(`Remove ${member.username} from this shared Budget? They will keep their app account but start with a separate empty Budget.`)) removeMember.mutate(member.id); }}>Remove</button>}</div></div>)}</div>
        {family?.role === "member" && <div className="shared-budget-leave"><p>You are a full member of <strong>{family.budget_owner_username}'s Budget</strong>. Leaving keeps your app account but starts you with a separate empty Budget.</p><button className="button secondary" type="button" disabled={leaveBudget.isPending} onClick={() => { if (window.confirm("Leave this shared Budget and start a separate private Budget?")) leaveBudget.mutate(); }}>{leaveBudget.isPending ? "Leaving…" : "Leave shared Budget"}</button></div>}
        {isAdmin && users.length > 0 && <details className="installation-users"><summary>All app users ({users.length})</summary><div className="family-users">{users.map((member) => <div className="family-user" key={member.id}><div><b>{member.username}</b><small>{member.email} · {member.google_connected ? "Google" : "Password"}{member.is_admin ? " · Admin" : ""}</small></div>{member.has_password && <button className="button ghost" type="button" disabled={reset.isPending} onClick={() => reset.mutate(member.id)}>Reset password</button>}</div>)}</div></details>}
        {invitations.length > 0 && <div className="pending-invites"><strong>Invite links</strong>{invitations.slice(0, 12).map((item) => <div className="family-user" key={item.id}><div><b>{item.label || `Invite #${item.id}`}</b><small>{item.invite_type === "shared" ? "Shared Budget" : "Independent app access"} · {item.status} · expires {dateTime(item.expires_at)}</small></div>{item.status === "pending" && <button className="button ghost" type="button" disabled={revoke.isPending} onClick={() => revoke.mutate(item.id)}>Revoke</button>}</div>)}</div>}
      </>}
    </article>
  );
}

function DeleteAccountCard({ hasPassword, onDeleted }: { hasPassword: boolean; onDeleted: () => Promise<void> }) {
  const [open, setOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [password, setPassword] = useState("");
  const remove = useMutation({
    mutationFn: () => apiRequest<{ ok: boolean }>("/auth/account", { method: "DELETE", body: JSON.stringify({ confirmation, password: hasPassword ? password : null }) }),
    onSuccess: () => void onDeleted(),
  });
  return (
    <article className="panel security-card danger-card">
      <span className="eyebrow">Danger zone</span><h3>Delete Budget account</h3><p>Permanently deletes this user's accounts, transactions, budgets, goals, reports, Advisor history, and bank connections.</p>
      {!open ? <button className="button danger" type="button" onClick={() => setOpen(true)}>Delete my account</button> : <div className="form-stack danger-confirm"><label>Type DELETE<input value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>{hasPassword && <label>Current password<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>}<div><button className="button ghost" type="button" onClick={() => setOpen(false)}>Cancel</button><button className="button danger" type="button" disabled={confirmation !== "DELETE" || (hasPassword && !password) || remove.isPending} onClick={() => { if (window.confirm("Permanently delete this Budget account and its financial data?")) remove.mutate(); }}>{remove.isPending ? "Deleting…" : "Delete permanently"}</button></div></div>}
      {remove.error instanceof ApiError && <div className="inline-alert" role="alert">{remove.error.message}</div>}
    </article>
  );
}
