import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { NotificationPreferences } from "../api/types";
import { ErrorState, LoadingState } from "./States";
import { useToast } from "../toast/ToastContext";
import { MoneyInput } from "./MoneyInput";

export function NotificationSettings() {
  const queryClient = useQueryClient();
  const { pushToast } = useToast();
  const query = useQuery({
    queryKey: queryKeys.notificationPreferences,
    queryFn: () => apiRequest<NotificationPreferences>("/notifications/preferences"),
  });
  const [draft, setDraft] = useState<NotificationPreferences | null>(null);
  useEffect(() => { if (query.data) setDraft(query.data); }, [query.data]);
  const save = useMutation({
    mutationFn: (payload: Partial<NotificationPreferences>) => apiRequest<NotificationPreferences>("/notifications/preferences", { method: "PATCH", body: JSON.stringify(payload) }),
    onSuccess: (value) => {
      queryClient.setQueryData(queryKeys.notificationPreferences, value);
      setDraft(value);
      pushToast("Notification preferences saved.", "success");
    },
  });

  if (query.isPending) return <section className="settings-notifications"><LoadingState label="Loading notification preferences" /></section>;
  if (query.isError) return <section className="settings-notifications"><ErrorState title="Notification preferences unavailable" message="Budget could not load your alert preferences." onRetry={() => void query.refetch()} /></section>;
  if (!draft) return <section className="settings-notifications"><LoadingState label="Loading notification preferences" /></section>;

  const set = <K extends keyof NotificationPreferences>(key: K, value: NotificationPreferences[K]) => setDraft((current) => current ? { ...current, [key]: value } : current);
  const payload = {
    in_app_enabled: draft.in_app_enabled,
    email_enabled: draft.email_delivery_available && draft.email_enabled,
    spending_alerts: draft.spending_alerts,
    forecast_alerts: draft.forecast_alerts,
    goal_milestones: draft.goal_milestones,
    recurring_changes: draft.recurring_changes,
    large_transaction_alerts: draft.large_transaction_alerts,
    large_transaction_threshold: draft.large_transaction_threshold,
    weekly_summary: draft.weekly_summary,
    monthly_summary: draft.monthly_summary,
  };
  const error = save.error instanceof ApiError ? save.error.message : null;

  return (
    <section className="settings-notifications" aria-labelledby="notifications-settings-heading">
      <div className="settings-section-heading">
        <div><span className="eyebrow">Notifications</span><h2 id="notifications-settings-heading">Financial alerts</h2><p>Choose what Budget should surface. Alert decisions are deterministic; Gemini does not decide when to notify you.</p></div>
      </div>
      {error && <div className="inline-alert" role="alert">{error}</div>}
      <div className="notification-settings-grid">
        <article className="panel notification-settings-card">
          <div className="security-card-heading"><div><span className="eyebrow">Delivery</span><h3>Where alerts appear</h3></div></div>
          <div className="advisor-setting-list">
            <label><span><strong>In-app notifications</strong><small>Show alerts in Budget's notification inbox and unread badge.</small></span><input type="checkbox" checked={draft.in_app_enabled} onChange={(event) => set("in_app_enabled", event.target.checked)} /></label>
            <label className={!draft.email_delivery_available ? "disabled-setting" : ""}><span><strong>Email notifications</strong><small>{draft.email_delivery_available ? "Send enabled alerts to your Budget account email." : "SMTP email delivery is not configured on this server yet."}</small></span><input type="checkbox" disabled={!draft.email_delivery_available} checked={draft.email_enabled && draft.email_delivery_available} onChange={(event) => set("email_enabled", event.target.checked)} /></label>
          </div>
        </article>
        <article className="panel notification-settings-card">
          <div className="security-card-heading"><div><span className="eyebrow">Alerts</span><h3>Financial changes</h3></div></div>
          <div className="advisor-setting-list compact-settings">
            <label><span><strong>Spending & safe-to-spend</strong><small>Over-budget categories and thin/negative spending cushion.</small></span><input type="checkbox" checked={draft.spending_alerts} onChange={(e) => set("spending_alerts", e.target.checked)} /></label>
            <label><span><strong>Low-cash forecasts</strong><small>Projected cash falling below your protected reserve.</small></span><input type="checkbox" checked={draft.forecast_alerts} onChange={(e) => set("forecast_alerts", e.target.checked)} /></label>
            <label><span><strong>Goal milestones</strong><small>25%, 50%, 75%, and fully funded progress.</small></span><input type="checkbox" checked={draft.goal_milestones} onChange={(e) => set("goal_milestones", e.target.checked)} /></label>
            <label><span><strong>Recurring changes</strong><small>Detected recurring charges that materially increase.</small></span><input type="checkbox" checked={draft.recurring_changes} onChange={(e) => set("recurring_changes", e.target.checked)} /></label>
          </div>
        </article>
        <article className="panel notification-settings-card">
          <div className="security-card-heading"><div><span className="eyebrow">Transactions</span><h3>Large purchases</h3></div></div>
          <div className="advisor-setting-list compact-settings">
            <label><span><strong>Large transaction alerts</strong><small>Off by default. Alert on newly imported expenses above your threshold.</small></span><input type="checkbox" checked={draft.large_transaction_alerts} onChange={(e) => set("large_transaction_alerts", e.target.checked)} /></label>
          </div>
          <label className={!draft.large_transaction_alerts ? "disabled-setting" : ""}>Alert threshold<MoneyInput min="1" disabled={!draft.large_transaction_alerts} value={draft.large_transaction_threshold} onValueChange={(value) => set("large_transaction_threshold", value)} /></label>
        </article>
        <article className="panel notification-settings-card">
          <div className="security-card-heading"><div><span className="eyebrow">Summaries</span><h3>Financial reviews</h3></div></div>
          <div className="advisor-setting-list compact-settings">
            <label><span><strong>Weekly summary</strong><small>Income, spending, net cash flow, and active insights for the prior week.</small></span><input type="checkbox" checked={draft.weekly_summary} onChange={(e) => set("weekly_summary", e.target.checked)} /></label>
            <label><span><strong>Monthly summary</strong><small>A compact review of the prior calendar month.</small></span><input type="checkbox" checked={draft.monthly_summary} onChange={(e) => set("monthly_summary", e.target.checked)} /></label>
          </div>
        </article>
      </div>
      <div className="form-actions end notification-settings-actions"><button className="button primary" type="button" disabled={save.isPending} onClick={() => save.mutate(payload)}>{save.isPending ? "Saving…" : "Save notification preferences"}</button></div>
    </section>
  );
}
