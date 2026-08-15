import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useState } from "react";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { BudgetNotification, NotificationList } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { useToast } from "../toast/ToastContext";

function severityLabel(value: BudgetNotification["severity"]): string {
  if (value === "critical") return "Critical";
  if (value === "important") return "Important";
  if (value === "opportunity") return "Opportunity";
  return "Info";
}

function NotificationRow({ item, onRead, onDismiss }: { item: BudgetNotification; onRead: () => void; onDismiss: () => void }) {
  return (
    <article className={`panel notification-row${item.read_at ? " read" : " unread"}`}>
      <div className="notification-accent" aria-hidden="true" />
      <div className="notification-copy">
        <div className="notification-meta">
          <span className={`notification-severity ${item.severity}`}>{severityLabel(item.severity)}</span>
          <time dateTime={item.occurred_at}>{new Date(item.occurred_at).toLocaleString()}</time>
          {item.email_sent_at && <span className="notification-email-status">Emailed</span>}
        </div>
        <h2>{item.title}</h2>
        <p>{item.body}</p>
        <div className="notification-actions">
          {item.action_route && <Link className="button secondary" to={item.action_route}>Open</Link>}
          {!item.read_at && <button className="button ghost" type="button" onClick={onRead}>Mark read</button>}
          <button className="button ghost" type="button" onClick={onDismiss}>Dismiss</button>
        </div>
      </div>
    </article>
  );
}

export function NotificationsPage() {
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const queryClient = useQueryClient();
  const { pushToast } = useToast();
  const list = useQuery({
    queryKey: queryKeys.notifications(filter),
    queryFn: () => apiRequest<NotificationList>(`/notifications?status=${filter}&limit=100`),
    refetchInterval: 60_000,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["notifications"] });
    void queryClient.invalidateQueries({ queryKey: queryKeys.notificationCount });
  };

  const update = useMutation({
    mutationFn: ({ id, body }: { id: number; body: Record<string, boolean> }) => apiRequest(`/notifications/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
    onSuccess: refresh,
  });
  const readAll = useMutation({
    mutationFn: () => apiRequest<{ ok: boolean }>("/notifications/read-all", { method: "POST" }),
    onSuccess: () => { refresh(); pushToast("Notifications marked as read.", "success"); },
  });

  return (
    <div className="page-container notifications-page">
      <PageHeader
        title="Notifications"
        description="Deterministic financial alerts, milestones, and summaries from Budget."
        actions={<div className="notification-header-actions"><button className="button secondary" type="button" disabled={!list.data?.unread_count || readAll.isPending} onClick={() => readAll.mutate()}>Mark all read</button><Link className="button secondary" to="/settings">Preferences</Link></div>}
      />
      <div className="notification-filter-bar" role="tablist" aria-label="Notification filter">
        <button className={filter === "all" ? "active" : ""} type="button" onClick={() => setFilter("all")}>All</button>
        <button className={filter === "unread" ? "active" : ""} type="button" onClick={() => setFilter("unread")}>Unread {list.data?.unread_count ? `(${list.data.unread_count})` : ""}</button>
      </div>
      {list.isPending && <LoadingState label="Loading notifications" />}
      {list.isError && <ErrorState title="Notifications unavailable" message="Budget could not load your notification inbox." onRetry={() => void list.refetch()} />}
      {list.data && !list.data.notifications.length && <EmptyState title={filter === "unread" ? "You're all caught up" : "No notifications yet"} message={filter === "unread" ? "There are no unread financial alerts." : "Budget will put important spending, forecast, recurring, and goal updates here."} />}
      {list.data && list.data.notifications.length > 0 && <div className="notification-list">{list.data.notifications.map((item) => <NotificationRow key={item.id} item={item} onRead={() => update.mutate({ id: item.id, body: { read: true } })} onDismiss={() => update.mutate({ id: item.id, body: { dismissed: true } })} />)}</div>}
    </div>
  );
}
