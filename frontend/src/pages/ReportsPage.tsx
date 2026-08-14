import { useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type {
  ReportRangeKey,
  ReportsBudget,
  ReportsCashFlowPoint,
  ReportsOverview,
  ReportsSpending,
} from "../api/types";
import { Amount } from "../components/Amount";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { formatDate, formatMoney, formatPercent, monthLabel, numberFromMoney } from "../lib/format";

type ReportTab = "overview" | "spending" | "budget" | "goals";

const ranges: Array<{ key: ReportRangeKey; label: string; days: number }> = [
  { key: "30d", label: "30 days", days: 30 },
  { key: "3m", label: "3 months", days: 92 },
  { key: "6m", label: "6 months", days: 184 },
  { key: "ytd", label: "YTD", days: 366 },
  { key: "1y", label: "1 year", days: 365 },
];

function percentLabel(value: string | null) {
  return value === null ? "No prior baseline" : formatPercent(value);
}

function changeClass(value: string | null, inverse = false) {
  if (value === null) return "neutral";
  const amount = numberFromMoney(value);
  if (amount === 0) return "neutral";
  const good = inverse ? amount < 0 : amount > 0;
  return good ? "positive" : "negative";
}

function periodLabel(period: string) {
  if (/^\d{4}-\d{2}$/.test(period)) return monthLabel(period).replace(/ \d{4}$/, "");
  return formatDate(period);
}

function transactionsLink(start: string, end: string, params: Record<string, string | number | null>) {
  const search = new URLSearchParams({ start_date: start, end_date: end, sort: "date", direction: "desc" });
  Object.entries(params).forEach(([key, value]) => { if (value !== null && String(value)) search.set(key, String(value)); });
  return `/transactions?${search.toString()}`;
}

function CashFlowChart({ rows, currency }: { rows: ReportsCashFlowPoint[]; currency: string }) {
  if (!rows.length) return <EmptyState title="No cash-flow history in this range" message="Income and spending will appear here as transactions are recorded." />;
  const maximum = Math.max(1, ...rows.flatMap((row) => [numberFromMoney(row.income), numberFromMoney(row.spending)]));
  return (
    <div className="reports-chart-scroll">
      <div className="reports-bar-chart" style={{ "--report-columns": rows.length } as CSSProperties} aria-label="Income versus spending chart">
        {rows.map((row) => {
          const income = numberFromMoney(row.income);
          const spending = numberFromMoney(row.spending);
          return (
            <div className="reports-chart-column" key={row.period}>
              <div className="reports-chart-bars">
                <span className="income-bar" style={{ height: `${Math.max(income > 0 ? 4 : 0, income / maximum * 100)}%` }} title={`Income ${formatMoney(row.income, currency)}`} />
                <span className="spending-bar" style={{ height: `${Math.max(spending > 0 ? 4 : 0, spending / maximum * 100)}%` }} title={`Spending ${formatMoney(row.spending, currency)}`} />
              </div>
              <small>{periodLabel(row.period)}</small>
            </div>
          );
        })}
      </div>
      <div className="reports-chart-legend"><span><i className="income-swatch" />Income</span><span><i className="spending-swatch" />Spending</span></div>
    </div>
  );
}

function OverviewReport({ data, days }: { data: ReportsOverview; days: number }) {
  return (
    <>
      <section className="reports-kpis" aria-label="Current financial snapshot">
        <article className="panel report-kpi"><span>Net worth</span><Amount value={data.current.net_worth} currency={data.currency} /><small>Across accounts in your reporting currency</small></article>
        <article className="panel report-kpi"><span>Cash available</span><Amount value={data.current.cash_available} currency={data.currency} /><small>Depository cash available now</small></article>
        <article className="panel report-kpi"><span>Safe to spend</span><Amount value={data.current.safe_to_spend} currency={data.currency} /><small>After budget, recurring, goal, and debt reserves</small></article>
        <article className="panel report-kpi"><span>Total debt</span><Amount value={data.current.total_debt} currency={data.currency} /><small>Active tracked debt balance</small></article>
      </section>
      <section className="panel reports-foundation">
        <div className="reports-section-heading"><div><span className="eyebrow">Historical foundation</span><h2>Daily financial snapshots</h2></div><span className="reports-range">Last {days} days</span></div>
        <p>Budget stores one owner-scoped snapshot per local calendar day so this timeline preserves what your plan, debt, cash, and forecasts looked like at each point in time.</p>
        {data.history.length === 0 ? (
          <EmptyState title="History starts with the first scheduled snapshot" message="The reporting worker will build this timeline automatically." />
        ) : (
          <div className="reports-snapshot-table-wrap"><table className="reports-snapshot-table"><thead><tr><th>Date</th><th>Net worth</th><th>Safe to spend</th><th>Total debt</th><th>90-day projection</th></tr></thead><tbody>{data.history.slice(-14).reverse().map((snapshot) => <tr key={snapshot.snapshot_date}><td>{formatDate(snapshot.snapshot_date, true)}</td><td><Amount value={snapshot.net_worth} currency={data.currency} /></td><td><Amount value={snapshot.safe_to_spend} currency={data.currency} /></td><td><Amount value={snapshot.total_debt} currency={data.currency} /></td><td><Amount value={snapshot.projected_90_day} currency={data.currency} /></td></tr>)}</tbody></table></div>
        )}
      </section>
    </>
  );
}

function SpendingReport({ data }: { data: ReportsSpending }) {
  const recurringTotal = Math.max(numberFromMoney(data.recurring.total), 1);
  const recurringShare = numberFromMoney(data.recurring.recurring) / recurringTotal * 100;
  const maxCategory = Math.max(1, ...data.categories.map((row) => numberFromMoney(row.amount)));
  return (
    <div className="reports-stack">
      <section className="reports-kpis">
        <article className="panel report-kpi"><span>Income</span><Amount value={data.summary.income} currency={data.currency} /><small className={changeClass(data.summary.income_change_pct)}>vs prior period {percentLabel(data.summary.income_change_pct)}</small></article>
        <article className="panel report-kpi"><span>Spending</span><Amount value={data.summary.spending} currency={data.currency} /><small className={changeClass(data.summary.spending_change_pct, true)}>vs prior period {percentLabel(data.summary.spending_change_pct)}</small></article>
        <article className="panel report-kpi"><span>Net cash flow</span><Amount value={data.summary.net_cash_flow} currency={data.currency} signed /><small>Savings rate {percentLabel(data.summary.savings_rate)}</small></article>
        <article className="panel report-kpi"><span>Projected month spend</span><Amount value={data.summary.projected_month_spending} currency={data.currency} /><small>Current MTD <Amount value={data.summary.current_month_spending} currency={data.currency} /></small></article>
      </section>

      <section className="panel reports-analytics-panel">
        <div className="reports-section-heading"><div><span className="eyebrow">Cash flow</span><h2>Income vs spending</h2></div><span className="reports-range">{data.range.label}</span></div>
        <CashFlowChart rows={data.series} currency={data.currency} />
      </section>

      <div className="reports-two-column">
        <section className="panel reports-analytics-panel">
          <div className="reports-section-heading"><div><span className="eyebrow">Mix</span><h2>Recurring vs discretionary</h2></div></div>
          <div className="reports-split-bar" aria-label="Recurring versus discretionary spending"><span style={{ width: `${Math.max(0, Math.min(100, recurringShare))}%` }} /><i /></div>
          <div className="reports-split-values"><div><span>Recurring</span><Amount value={data.recurring.recurring} currency={data.currency} /></div><div><span>Discretionary</span><Amount value={data.recurring.discretionary} currency={data.currency} /></div></div>
        </section>
        <section className="panel reports-analytics-panel">
          <div className="reports-section-heading"><div><span className="eyebrow">Change</span><h2>Spending movement</h2></div></div>
          <div className="reports-callout"><strong className={changeClass(data.summary.spending_change_amount, true)}>{formatMoney(data.summary.spending_change_amount, data.currency, { showSign: true })}</strong><span>versus {formatDate(data.range.previous_start, true)} – {formatDate(data.range.previous_end, true)}</span></div>
        </section>
      </div>

      <section className="panel reports-analytics-panel">
        <div className="reports-section-heading"><div><span className="eyebrow">Categories</span><h2>Where your money went</h2></div><span className="reports-range">Click a category to drill through</span></div>
        {data.categories.length ? <div className="reports-category-list">{data.categories.map((row) => {
          const route = row.category_id ? transactionsLink(data.range.start, data.range.end, { category_id: row.category_id, kind: "expense" }) : transactionsLink(data.range.start, data.range.end, { kind: "expense" });
          return <Link className="reports-category-row" to={route} key={`${row.key}-${row.category_id ?? "other"}`}><div><strong>{row.name}</strong><small>{row.transaction_count} transactions · prior {formatMoney(row.previous_amount, data.currency)}</small></div><div className="reports-category-bar"><span style={{ width: `${Math.max(1, numberFromMoney(row.amount) / maxCategory * 100)}%` }} /></div><Amount value={row.amount} currency={data.currency} /><span className={`reports-delta ${changeClass(row.change_pct, true)}`}>{row.change_pct === null ? "new" : formatPercent(row.change_pct)}</span></Link>;
        })}</div> : <EmptyState title="No spending in this range" message="Expense categories will appear after transactions are recorded." />}
      </section>

      <section className="panel reports-analytics-panel">
        <div className="reports-section-heading"><div><span className="eyebrow">Merchants</span><h2>Top merchants</h2></div></div>
        {data.top_merchants.length ? <div className="reports-table-wrap"><table className="reports-data-table"><thead><tr><th>Merchant</th><th>Category</th><th>Transactions</th><th>Spent</th></tr></thead><tbody>{data.top_merchants.map((row) => <tr key={row.name}><td><Link className="text-link" to={transactionsLink(data.range.start, data.range.end, { search: row.name, kind: "expense" })}>{row.name}</Link></td><td>{row.category}</td><td>{row.transaction_count}</td><td><Amount value={row.amount} currency={data.currency} /></td></tr>)}</tbody></table></div> : <EmptyState title="No merchants to rank" message="Merchant analytics will appear with expense transactions." />}
      </section>
    </div>
  );
}

function BudgetReport({ data }: { data: ReportsBudget }) {
  const maximum = Math.max(1, ...data.months.flatMap((row) => [numberFromMoney(row.budgeted), numberFromMoney(row.spent)]));
  return (
    <div className="reports-stack">
      {!data.has_annual_plan && <div className="info-banner">No annual plan is saved for {data.year}. Budget is still comparing monthly plans and actual activity where available.</div>}
      <section className="reports-kpis">
        <article className="panel report-kpi"><span>YTD planned income</span><Amount value={data.summary.ytd_planned_income} currency={data.currency} /><small>Actual <Amount value={data.summary.actual_income} currency={data.currency} /></small></article>
        <article className="panel report-kpi"><span>Annual budget</span><Amount value={data.summary.budgeted} currency={data.currency} /><small>Used {percentLabel(data.summary.budget_utilization_pct)}</small></article>
        <article className="panel report-kpi"><span>Spent YTD</span><Amount value={data.summary.spent} currency={data.currency} /><small>Remaining <Amount value={data.summary.remaining} currency={data.currency} /></small></article>
        <article className="panel report-kpi"><span>Projected year-end spend</span><Amount value={data.summary.projected_year_end_spend} currency={data.currency} /><small>Based on current YTD pace</small></article>
      </section>

      <section className="panel reports-analytics-panel">
        <div className="reports-section-heading"><div><span className="eyebrow">Monthly performance</span><h2>Budget vs actual</h2></div><span className="reports-range">{data.range.label}</span></div>
        {data.months.length ? <div className="reports-chart-scroll"><div className="reports-bar-chart budget-chart" style={{ "--report-columns": data.months.length } as CSSProperties}>{data.months.map((row) => <div className="reports-chart-column" key={row.month}><div className="reports-chart-bars"><span className="budget-bar" style={{ height: `${Math.max(numberFromMoney(row.budgeted) > 0 ? 4 : 0, numberFromMoney(row.budgeted) / maximum * 100)}%` }} title={`Budget ${formatMoney(row.budgeted, data.currency)}`} /><span className="spending-bar" style={{ height: `${Math.max(numberFromMoney(row.spent) > 0 ? 4 : 0, numberFromMoney(row.spent) / maximum * 100)}%` }} title={`Spent ${formatMoney(row.spent, data.currency)}`} /></div><small>{monthLabel(row.month).replace(/ \d{4}$/, "")}</small></div>)}</div><div className="reports-chart-legend"><span><i className="budget-swatch" />Budget</span><span><i className="spending-swatch" />Actual</span></div></div> : <EmptyState title="No monthly budget periods" message="Monthly budget performance will appear once a plan exists." />}
      </section>

      <section className="panel reports-analytics-panel">
        <div className="reports-section-heading"><div><span className="eyebrow">Category performance</span><h2>Annual budget utilization</h2></div><span className="reports-range">Drill through to transactions</span></div>
        {data.categories.length ? <div className="reports-table-wrap"><table className="reports-data-table"><thead><tr><th>Category</th><th>YTD plan</th><th>Spent</th><th>YTD variance</th><th>Annual used</th></tr></thead><tbody>{data.categories.map((row) => <tr key={row.category_id}><td><Link className="text-link" to={transactionsLink(`${data.year}-01-01`, data.range.end, { category_id: row.category_id, kind: "expense" })}>{row.name}</Link></td><td><Amount value={row.ytd_planned_amount} currency={data.currency} /></td><td><Amount value={row.spent_amount} currency={data.currency} /></td><td><Amount value={row.ytd_variance} currency={data.currency} signed /></td><td>{percentLabel(row.percent_used)}</td></tr>)}</tbody></table></div> : <EmptyState title="No category budget data" message="Create an annual or monthly budget to populate category performance." />}
      </section>
    </div>
  );
}

export function ReportsPage() {
  const [tab, setTab] = useState<ReportTab>("overview");
  const [range, setRange] = useState<ReportRangeKey>("6m");
  const days = ranges.find((item) => item.key === range)?.days ?? 184;
  const overview = useQuery({ queryKey: queryKeys.reportsOverview(days), queryFn: () => apiRequest<ReportsOverview>(`/reports/overview?days=${days}`), staleTime: 60_000, enabled: tab === "overview" });
  const spending = useQuery({ queryKey: queryKeys.reportsSpending(range), queryFn: () => apiRequest<ReportsSpending>(`/reports/spending?range=${range}`), staleTime: 60_000, enabled: tab === "spending" });
  const budget = useQuery({ queryKey: queryKeys.reportsBudget(range), queryFn: () => apiRequest<ReportsBudget>(`/reports/budget?range=${range}`), staleTime: 60_000, enabled: tab === "budget" });
  const activeQuery = tab === "overview" ? overview : tab === "spending" ? spending : budget;

  return (
    <div className="page-container reports-page">
      <PageHeader title="Reports" description="Historical financial analytics built from Budget's deterministic calculations." />
      <div className="reports-toolbar">
        <div className="segmented-control reports-tabs" aria-label="Report section">
          <button type="button" className={tab === "overview" ? "active" : ""} onClick={() => setTab("overview")}>Overview</button>
          <button type="button" className={tab === "spending" ? "active" : ""} onClick={() => setTab("spending")}>Spending</button>
          <button type="button" className={tab === "budget" ? "active" : ""} onClick={() => setTab("budget")}>Budget</button>
          <button type="button" disabled title="Goals & Debt analytics arrive in the next 3D checkpoint">Goals &amp; Debt</button>
        </div>
        <div className="segmented-control reports-range-control" aria-label="Report range">{ranges.map((item) => <button type="button" key={item.key} className={range === item.key ? "active" : ""} onClick={() => setRange(item.key)}>{item.label}</button>)}</div>
      </div>

      {activeQuery.isPending && <LoadingState label="Building your financial report" />}
      {activeQuery.isError && <ErrorState message="Reports could not be loaded." onRetry={() => void activeQuery.refetch()} />}
      {tab === "overview" && overview.data && <OverviewReport data={overview.data} days={days} />}
      {tab === "spending" && spending.data && <SpendingReport data={spending.data} />}
      {tab === "budget" && budget.data && <BudgetReport data={budget.data} />}
    </div>
  );
}
