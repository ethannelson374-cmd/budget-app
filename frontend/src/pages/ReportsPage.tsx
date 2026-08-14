import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { ReportsOverview } from "../api/types";
import { Amount } from "../components/Amount";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { formatDate } from "../lib/format";

export function ReportsPage() {
  const days = 90;
  const report = useQuery({
    queryKey: queryKeys.reportsOverview(days),
    queryFn: () => apiRequest<ReportsOverview>(`/reports/overview?days=${days}`),
    staleTime: 60_000,
  });

  return (
    <div className="page-container reports-page">
      <PageHeader
        title="Reports"
        description="Historical financial analytics built from Budget's deterministic calculations."
      />
      <div className="segmented-control reports-tabs" aria-label="Report section">
        <button type="button" className="active">Overview</button>
        <button type="button" disabled>Spending</button>
        <button type="button" disabled>Budget</button>
        <button type="button" disabled>Goals &amp; Debt</button>
      </div>

      {report.isPending && <LoadingState label="Building your reporting overview" />}
      {report.isError && <ErrorState message="Reports could not be loaded." onRetry={() => void report.refetch()} />}
      {report.data && (
        <>
          <section className="reports-kpis" aria-label="Current financial snapshot">
            <article className="panel report-kpi"><span>Net worth</span><Amount value={report.data.current.net_worth} currency={report.data.currency} /><small>Across accounts in your reporting currency</small></article>
            <article className="panel report-kpi"><span>Cash available</span><Amount value={report.data.current.cash_available} currency={report.data.currency} /><small>Depository cash available now</small></article>
            <article className="panel report-kpi"><span>Safe to spend</span><Amount value={report.data.current.safe_to_spend} currency={report.data.currency} /><small>After budget, recurring, goal, and debt reserves</small></article>
            <article className="panel report-kpi"><span>Total debt</span><Amount value={report.data.current.total_debt} currency={report.data.currency} /><small>Active tracked debt balance</small></article>
          </section>

          <section className="panel reports-foundation">
            <div className="reports-section-heading">
              <div><span className="eyebrow">Historical foundation</span><h2>Daily financial snapshots</h2></div>
              <span className="reports-range">Last {days} days</span>
            </div>
            <p>Budget stores one owner-scoped snapshot per local calendar day. Repeated captures update today's row instead of creating duplicates, so future reports can compare what Budget knew at each point in time.</p>
            {report.data.history.length === 0 ? (
              <EmptyState title="History starts with the first scheduled snapshot" message="The reporting worker will build this timeline automatically. Transaction-based historical analytics will be added in the next 3D checkpoint." />
            ) : (
              <div className="reports-snapshot-table-wrap">
                <table className="reports-snapshot-table">
                  <thead><tr><th>Date</th><th>Net worth</th><th>Safe to spend</th><th>Total debt</th><th>90-day projection</th></tr></thead>
                  <tbody>{report.data.history.slice(-14).reverse().map((snapshot) => (
                    <tr key={snapshot.snapshot_date}>
                      <td>{formatDate(snapshot.snapshot_date, true)}</td>
                      <td><Amount value={snapshot.net_worth} currency={report.data.currency} /></td>
                      <td><Amount value={snapshot.safe_to_spend} currency={report.data.currency} /></td>
                      <td><Amount value={snapshot.total_debt} currency={report.data.currency} /></td>
                      <td><Amount value={snapshot.projected_90_day} currency={report.data.currency} /></td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
