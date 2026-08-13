import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { DashboardData, InsightsResponse, MonthlyBudgetView } from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { ErrorState, LoadingState, EmptyState } from "../components/States";
import { CashFlowChart } from "../components/CashFlowChart";
import { CategoryBars } from "../components/CategoryBars";
import { InsightCard } from "../components/InsightCard";
import { TransactionList } from "../components/TransactionList";
import { formatDateTime, formatMoney, formatPercent, currentMonth, maskAccount, monthLabel, numberFromMoney } from "../lib/format";
import { useState } from "react";

function shiftMonth(month: string, delta: number): string {
  const [year, monthNumber] = month.split("-").map(Number);
  const result = new Date(year, monthNumber - 1 + delta, 1);
  return `${result.getFullYear()}-${String(result.getMonth() + 1).padStart(2, "0")}`;
}

export function DashboardPage() {
  const [month, setMonth] = useState(currentMonth);
  const dashboard = useQuery({
    queryKey: queryKeys.dashboard(month),
    queryFn: () => apiRequest<DashboardData>(`/dashboard?month=${encodeURIComponent(month)}`),
  });
  const budget = useQuery({
    queryKey: queryKeys.budgetMonth(month),
    queryFn: () => apiRequest<MonthlyBudgetView>(`/budget/months/${month}`),
  });
  const insights = useQuery({
    queryKey: queryKeys.insights("active"),
    queryFn: () => apiRequest<InsightsResponse>("/insights/refresh", { method: "POST" }),
    staleTime: 60_000,
  });

  return (
    <div className="page-container dashboard-page">
      <PageHeader title="Dashboard" description={monthLabel(month)} actions={<div className="month-control"><button type="button" aria-label="Previous month" onClick={() => setMonth((value) => shiftMonth(value, -1))}>‹</button><label><span className="sr-only">Dashboard month</span><input type="month" value={month} max={currentMonth()} onChange={(event) => setMonth(event.target.value)} /></label><button type="button" aria-label="Next month" disabled={month >= currentMonth()} onClick={() => setMonth((value) => shiftMonth(value, 1))}>›</button></div>} />
      {dashboard.isPending && <LoadingState label="Calculating this month" />}
      {dashboard.isError && <ErrorState message="Your dashboard could not be loaded." onRetry={() => void dashboard.refetch()} />}
      {dashboard.data && <DashboardContent data={dashboard.data} budget={budget.data} insights={insights.data} />}
    </div>
  );
}

function DashboardContent({ data, budget, insights }: { data: DashboardData; budget?: MonthlyBudgetView; insights?: InsightsResponse }) {
  const { summary } = data;
  const savingsTone = summary.savings_rate === null ? "neutral" : numberFromMoney(summary.savings_rate) >= 0 ? "positive" : "negative";
  return (
    <>
      {data.excluded_currencies.length > 0 && <div className="notice-banner" role="status"><strong>Some balances are shown separately.</strong> Totals include {data.currency} only. Excluded: {data.excluded_currencies.join(", ")}.</div>}
      <section className="metric-grid" aria-label="Financial summary">
        <article className="metric-card featured"><span>Net worth</span><strong>{formatMoney(summary.net_worth, data.currency)}</strong><small>Across included accounts</small></article>
        <article className="metric-card"><span>Cash available</span><strong>{formatMoney(summary.cash_available, data.currency)}</strong><small>Available in cash accounts</small></article>
        <article className="metric-card"><span>Income</span><strong className="positive">{formatMoney(summary.income, data.currency)}</strong><small>This month</small></article>
        <article className="metric-card"><span>Spending</span><strong>{formatMoney(summary.spending, data.currency)}</strong><small>Transfers excluded</small></article>
        <article className="metric-card"><span>Net cash flow</span><strong className={numberFromMoney(summary.net_cash_flow) >= 0 ? "positive" : "negative"}>{formatMoney(summary.net_cash_flow, data.currency, { showSign: true })}</strong><small>Income less spending</small></article>
        <article className="metric-card"><span>Savings rate</span><strong className={savingsTone}>{formatPercent(summary.savings_rate)}</strong><small>{summary.savings_rate === null ? "No income this month" : "Of monthly income"}</small></article>
      </section>
      <div className="dashboard-grid">
        <section className="panel chart-panel"><div className="panel-heading"><div><span className="eyebrow">Daily movement</span><h2>Cash flow</h2></div><span className="as-of">As of {formatDateTime(data.as_of)}</span></div><CashFlowChart data={data.daily_cash_flow} currency={data.currency} /></section>
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">This month</span><h2>Top spending</h2></div></div><CategoryBars categories={data.spending_by_category} currency={data.currency} /></section>
      </div>
      {budget && budget.source !== "unplanned" && <section className="panel dashboard-budget-panel">
        <div className="panel-heading"><div><span className="eyebrow">Monthly budget</span><h2>{formatMoney(budget.spent, budget.currency)} spent of {formatMoney(budget.available_with_rollover, budget.currency)}</h2></div><Link className="text-link" to="/budget">Open budget <span aria-hidden="true">→</span></Link></div>
        <div className="dashboard-budget-summary"><div><strong>{formatMoney(budget.remaining, budget.currency)}</strong><span>Remaining</span></div><div><strong>{formatMoney(budget.safe_to_spend, budget.currency)}</strong><span>Safe to spend</span></div><div><strong>{budget.categories.filter((row) => row.status === "close").length}</strong><span>Getting close</span></div><div><strong>{budget.categories.filter((row) => row.status === "over").length}</strong><span>Over budget</span></div></div>
      </section>}
      {insights && insights.insights.length > 0 && <section className="panel dashboard-insights">
        <div className="panel-heading"><div><span className="eyebrow">Financial intelligence</span><h2>What needs your attention</h2></div><Link className="text-link" to="/insights">View all {insights.active_count} <span aria-hidden="true">→</span></Link></div>
        <div className="dashboard-insight-list">{insights.insights.slice(0, 3).map((insight) => <InsightCard key={insight.id} insight={insight} compact />)}</div>
      </section>}
      <section className="panel recent-panel">
        <div className="panel-heading"><div><span className="eyebrow">Latest activity</span><h2>Recent transactions</h2></div><Link className="text-link" to="/transactions">View all <span aria-hidden="true">→</span></Link></div>
        {data.recent_transactions.length ? <TransactionList transactions={data.recent_transactions} compact /> : <EmptyState title="No transactions yet" message="Transactions will appear here when financial data is available." />}
      </section>
      <section className="panel dashboard-accounts">
        <div className="panel-heading"><div><span className="eyebrow">Balance snapshot</span><h2>Accounts</h2></div><Link className="text-link" to="/accounts">View all <span aria-hidden="true">→</span></Link></div>
        {data.accounts.length ? <div className="dashboard-account-list">{data.accounts.slice(0, 4).map((account) => <article key={account.id}><div><strong>{account.name}</strong><span>{account.institution ?? account.account_type} · {maskAccount(account.mask)}</span></div><strong>{formatMoney(account.current_balance, account.currency)}</strong></article>)}</div> : <p className="dashboard-account-empty">No accounts are available yet.</p>}
      </section>
    </>
  );
}
