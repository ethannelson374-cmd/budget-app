import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { InsightItem, InsightsResponse, InsightStatus } from "../api/types";
import { InsightCard } from "../components/InsightCard";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";

type InsightFilter = InsightStatus | "all";

const filterLabels: Record<InsightFilter, string> = {
  active: "Active",
  dismissed: "Dismissed",
  resolved: "Resolved",
  all: "History",
};

export function InsightsPage({ embedded = false }: { embedded?: boolean } = {}) {
  const [filter, setFilter] = useState<InsightFilter>("active");
  const queryClient = useQueryClient();
  const insights = useQuery({
    queryKey: queryKeys.insights(filter),
    queryFn: () => filter === "active"
      ? apiRequest<InsightsResponse>("/insights/refresh", { method: "POST" })
      : apiRequest<InsightsResponse>(`/insights?status=${filter}`),
    staleTime: filter === "active" ? 60_000 : 10_000,
  });
  const statusMutation = useMutation({
    mutationFn: ({ insight, status }: { insight: InsightItem; status: "active" | "dismissed" }) =>
      apiRequest<InsightItem>(`/insights/${insight.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status }),
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["insights"] });
    },
  });
  const refresh = useMutation({
    mutationFn: () => apiRequest<InsightsResponse>("/insights/refresh", { method: "POST" }),
    onSuccess: async (data) => {
      queryClient.setQueryData(queryKeys.insights("active"), data);
      await queryClient.invalidateQueries({ queryKey: ["insights"] });
    },
  });
  const data = insights.data;
  const counts = data ? { active: data.active_count, dismissed: data.dismissed_count, resolved: data.resolved_count } : null;

  return (
    <div className={`page-container insights-page${embedded ? " embedded-page" : ""}`}>
      <PageHeader
        title="Insights"
        description="Deterministic signals from your spending, budget, recurring activity, goals, debt, and forecast."
        actions={<button className="button secondary" type="button" disabled={refresh.isPending} onClick={() => refresh.mutate()}>{refresh.isPending ? "Analyzing…" : "Refresh insights"}</button>}
      />
      <div className="insight-toolbar">
        <div className="segmented-control insight-filters" aria-label="Insight history filter">
          {(Object.keys(filterLabels) as InsightFilter[]).map((item) => (
            <button type="button" key={item} className={filter === item ? "active" : ""} onClick={() => setFilter(item)}>
              {filterLabels[item]}{counts && item !== "all" ? ` (${counts[item]})` : ""}
            </button>
          ))}
        </div>
        <p>No AI is calculating these numbers. Every insight is derived from Budget's own financial engines.</p>
      </div>
      {insights.isPending && <LoadingState label="Analyzing your financial signals" />}
      {insights.isError && <ErrorState message="Insights could not be loaded." onRetry={() => void insights.refetch()} />}
      {data && data.insights.length === 0 && <EmptyState title={filter === "active" ? "Nothing needs your attention right now" : `No ${filter} insights`} message={filter === "active" ? "Budget will surface material changes as your transactions, plans, and forecasts evolve." : "Insights will appear here as their status changes."} />}
      {data && data.insights.length > 0 && (
        <div className="insight-list">
          {data.insights.map((insight) => (
            <InsightCard
              key={insight.id}
              insight={insight}
              busy={statusMutation.isPending}
              onDismiss={(item) => statusMutation.mutate({ insight: item, status: "dismissed" })}
              onRestore={(item) => statusMutation.mutate({ insight: item, status: "active" })}
            />
          ))}
        </div>
      )}
    </div>
  );
}
