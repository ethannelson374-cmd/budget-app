import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { RecurringStreamsResponse } from "../api/types";
import { Amount } from "../components/Amount";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { PageHeader } from "../components/PageHeader";
import { formatDate } from "../lib/format";

export function RecurringPage() {
  const queryClient = useQueryClient();
  const recurring = useQuery({
    queryKey: queryKeys.recurring,
    queryFn: () => apiRequest<RecurringStreamsResponse>("/recurring"),
  });
  const rebuild = useMutation({
    mutationFn: () => apiRequest<RecurringStreamsResponse>("/recurring/rebuild", { method: "POST" }),
    onSuccess: (data) => queryClient.setQueryData(queryKeys.recurring, data),
  });

  return (
    <div className="page-container recurring-page">
      <PageHeader
        title="Recurring"
        description="Budget detects repeating income and expenses from your transaction history."
        actions={<button className="button secondary" type="button" disabled={rebuild.isPending} onClick={() => rebuild.mutate()}>{rebuild.isPending ? "Analyzing…" : "Reanalyze"}</button>}
      />
      {recurring.isPending && <LoadingState label="Analyzing recurring activity" />}
      {recurring.isError && <ErrorState message="Recurring activity could not be loaded." onRetry={() => void recurring.refetch()} />}
      {recurring.data && (
        <>
          <div className="summary-grid recurring-summary">
            <article className="metric-card"><span>Estimated monthly recurring outflow</span><Amount value={recurring.data.monthly_outflow_estimate} currency={recurring.data.currency} /><small>Based on detected cadence</small></article>
            <article className="metric-card"><span>Estimated monthly recurring inflow</span><Amount value={recurring.data.monthly_inflow_estimate} currency={recurring.data.currency} /><small>Paychecks and other repeating income</small></article>
            <article className="metric-card"><span>Detected streams</span><strong className="metric-value">{recurring.data.streams.length}</strong><small>Three or more matching occurrences</small></article>
          </div>
          {recurring.data.streams.length ? (
            <section className="panel recurring-panel">
              <div className="panel-heading"><div><span className="eyebrow">Pattern detection</span><h2>Expected activity</h2></div></div>
              <div className="recurring-list">
                {recurring.data.streams.map((stream) => {
                  const change = stream.price_change_pct ? Number(stream.price_change_pct) : 0;
                  return (
                    <article className="recurring-row" key={stream.id}>
                      <div><strong>{stream.display_name}</strong><span>{stream.account.name} · {stream.cadence}</span></div>
                      <div><Amount value={stream.average_amount} currency={stream.account.currency} /><span>Average</span></div>
                      <div><strong>{formatDate(stream.next_expected_date)}</strong><span>Expected next</span></div>
                      <div className={Math.abs(change) >= 5 ? "recurring-change warning" : "recurring-change"}><strong>{change ? `${change > 0 ? "+" : ""}${change.toFixed(1)}%` : "—"}</strong><span>Latest vs prior avg</span></div>
                    </article>
                  );
                })}
              </div>
            </section>
          ) : <EmptyState title="No recurring patterns yet" message="Budget looks for at least three similar posted transactions with a recognizable cadence." />}
        </>
      )}
    </div>
  );
}
