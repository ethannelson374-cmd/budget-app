import { useState, type CSSProperties, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type {
  ReportExport,
  ReportExportList,
  ReportRangeKey,
  ReportSectionKey,
  ReportsBudget,
  ReportsCashFlowPoint,
  ReportsGoalsDebt,
  ReportsOverview,
  ReportsSpending,
  SavedReport,
  SavedReportList,
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


function MetricLineChart({
  rows,
  value,
  currency,
  label,
}: {
  rows: ReportsGoalsDebt["trajectory"];
  value: (row: ReportsGoalsDebt["trajectory"][number]) => string;
  currency: string;
  label: string;
}) {
  if (!rows.length) return <EmptyState title="History is still being collected" message="Daily reporting snapshots will build this trend automatically." />;
  const values = rows.map((row) => numberFromMoney(value(row)));
  const low = Math.min(...values, 0);
  const high = Math.max(...values, 1);
  const span = Math.max(high - low, 1);
  const points = rows.map((row, index) => {
    const x = rows.length === 1 ? 360 : 28 + index / (rows.length - 1) * 664;
    const y = 190 - ((numberFromMoney(value(row)) - low) / span) * 150;
    return `${x},${y}`;
  }).join(" ");
  return (
    <div className="reports-line-chart-wrap">
      <svg className="reports-line-chart" viewBox="0 0 720 220" role="img" aria-label={label}>
        <line x1="28" y1="190" x2="692" y2="190" className="reports-axis" />
        <polyline points={points} className="reports-line-primary" />
        {points.split(" ").map((point, index) => {
          const [cx, cy] = point.split(",");
          return <circle key={`${rows[index].date}-${index}`} cx={cx} cy={cy} r="4" className="reports-line-dot"><title>{formatDate(rows[index].date, true)} · {formatMoney(value(rows[index]), currency)}</title></circle>;
        })}
      </svg>
      <div className="reports-line-chart-labels"><span>{formatDate(rows[0].date, true)}</span><strong>{formatMoney(value(rows[rows.length - 1]), currency)}</strong><span>{formatDate(rows[rows.length - 1].date, true)}</span></div>
    </div>
  );
}

function GoalsDebtReport({ data }: { data: ReportsGoalsDebt }) {
  const goalProgress = data.summary.goal_progress_pct === null ? "—" : formatPercent(data.summary.goal_progress_pct);
  return (
    <div className="reports-stack">
      <section className="reports-kpis">
        <article className="panel report-kpi"><span>Goal progress</span><strong className="amount positive">{goalProgress}</strong><small><Amount value={data.summary.goal_current} currency={data.currency} /> of <Amount value={data.summary.goal_target} currency={data.currency} /></small></article>
        <article className="panel report-kpi"><span>Total debt</span><Amount value={data.summary.total_debt} currency={data.currency} /><small>Planned payment <Amount value={data.summary.planned_monthly_debt_payment} currency={data.currency} />/month</small></article>
        <article className="panel report-kpi"><span>Interest saved</span><Amount value={data.summary.interest_saved} currency={data.currency} /><small>Compared with minimum-only payoff</small></article>
        <article className="panel report-kpi"><span>90-day projected cash</span><Amount value={data.summary.projected_90_day} currency={data.currency} /><small>Reserve target <Amount value={data.summary.reserve_balance} currency={data.currency} /></small></article>
      </section>

      <div className="reports-two-column">
        <section className="panel reports-analytics-panel">
          <div className="reports-section-heading"><div><span className="eyebrow">Goals</span><h2>Goal balance trajectory</h2></div><span className="reports-range">{data.range.label}</span></div>
          <MetricLineChart rows={data.trajectory} value={(row) => row.goal_current} currency={data.currency} label="Goal balance history" />
        </section>
        <section className="panel reports-analytics-panel">
          <div className="reports-section-heading"><div><span className="eyebrow">Debt</span><h2>Debt balance trajectory</h2></div><span className="reports-range">{data.range.label}</span></div>
          <MetricLineChart rows={data.trajectory} value={(row) => row.total_debt} currency={data.currency} label="Debt balance history" />
        </section>
      </div>

      <section className="panel reports-analytics-panel">
        <div className="reports-section-heading"><div><span className="eyebrow">Goals</span><h2>Active goal progress</h2></div><span className="reports-range">Contributed {formatMoney(data.summary.goal_contributions_in_range, data.currency)} in range</span></div>
        {data.goals.length ? <div className="reports-goal-list">{data.goals.map((goal) => {
          const progress = Math.max(0, Math.min(100, numberFromMoney(goal.progress_pct)));
          return <article className="reports-goal-row" key={goal.id}><div className="reports-goal-heading"><div><strong>{goal.name}</strong><small>{goal.goal_type.replaceAll("_", " ")} · projected {goal.projected_date ? formatDate(goal.projected_date, true) : "—"}</small></div><span>{formatPercent(goal.progress_pct)}</span></div><div className="reports-goal-progress"><span style={{ width: `${progress}%` }} /></div><div className="reports-goal-meta"><span><Amount value={goal.current_amount} currency={data.currency} /> of <Amount value={goal.target_amount} currency={data.currency} /></span><span><Amount value={goal.monthly_contribution} currency={data.currency} />/mo</span><span>{formatMoney(goal.contributed_in_range, data.currency)} added in range</span></div></article>;
        })}</div> : <EmptyState title="No active goals" message="Create a goal on the Plan page to track progress here." />}
      </section>

      <section className="panel reports-analytics-panel">
        <div className="reports-section-heading"><div><span className="eyebrow">Debt payoff</span><h2>Current payoff plan</h2></div><span className="reports-range">Debt-free {data.summary.planned_debt_free_date ? formatDate(data.summary.planned_debt_free_date, true) : "—"}</span></div>
        {data.debts.length ? <div className="reports-table-wrap"><table className="reports-data-table"><thead><tr><th>Debt</th><th>Balance</th><th>APR</th><th>Payment</th><th>Planned payoff</th><th>Interest saved</th></tr></thead><tbody>{data.debts.map((debt) => <tr key={debt.id}><td>{debt.name}</td><td><Amount value={debt.balance} currency={data.currency} /></td><td>{formatPercent(debt.apr)}</td><td><Amount value={debt.planned_payment} currency={data.currency} /></td><td>{debt.planned_payoff_date ? formatDate(debt.planned_payoff_date, true) : "—"}</td><td><Amount value={debt.interest_saved} currency={data.currency} /></td></tr>)}</tbody></table></div> : <EmptyState title="No active debt" message="Tracked debts will appear here with payoff timing and interest savings." />}
      </section>

      <section className="panel reports-analytics-panel">
        <div className="reports-section-heading"><div><span className="eyebrow">Forecast</span><h2>30 / 60 / 90-day outlook</h2></div><span className="reports-range">Deterministic forecast</span></div>
        <div className="reports-forecast-grid">{data.forecast.map((row) => <article className="reports-forecast-card" key={row.days}><span>{row.days} days</span><Amount value={row.projected_balance} currency={data.currency} /><small>{formatDate(row.date, true)} · <span className={changeClass(row.above_reserve)}>reserve delta {formatMoney(row.above_reserve, data.currency, { showSign: true })}</span></small></article>)}</div>
      </section>

      <section className="panel reports-analytics-panel">
        <div className="reports-section-heading"><div><span className="eyebrow">Calibration</span><h2>Forecast accuracy</h2></div><span className="reports-range">{data.summary.forecast_accuracy_pct === null ? "Collecting history" : `Average ${formatPercent(data.summary.forecast_accuracy_pct)}`}</span></div>
        {data.accuracy.length ? <div className="reports-table-wrap"><table className="reports-data-table"><thead><tr><th>Forecast made</th><th>Horizon</th><th>Predicted</th><th>Actual spendable cash</th><th>Error</th><th>Accuracy</th></tr></thead><tbody>{data.accuracy.map((row) => <tr key={`${row.origin_date}-${row.horizon_days}`}><td>{formatDate(row.origin_date, true)}</td><td>{row.horizon_days} days</td><td><Amount value={row.predicted_balance} currency={data.currency} /></td><td><Amount value={row.actual_balance} currency={data.currency} /></td><td><Amount value={row.error} currency={data.currency} signed /></td><td>{formatPercent(row.accuracy_pct)}</td></tr>)}</tbody></table></div> : <EmptyState title="Forecast accuracy needs time" message="Once a 30, 60, or 90-day forecast matures, Budget will compare it with the actual spendable cash captured on that date." />}
      </section>
    </div>
  );
}

const reportSectionLabels: Record<ReportSectionKey, string> = {
  overview: "Overview",
  spending: "Spending & Cash Flow",
  budget: "Budget Performance",
  goals: "Goals & Debt",
};

function reportTabFromSection(section: ReportSectionKey): ReportTab {
  return section;
}

function ReportSectionsPicker({ sections, onChange }: { sections: ReportSectionKey[]; onChange: (sections: ReportSectionKey[]) => void }) {
  const toggle = (section: ReportSectionKey) => {
    if (sections.includes(section)) {
      if (sections.length === 1) return;
      onChange(sections.filter((item) => item !== section));
    } else {
      onChange([...sections, section]);
    }
  };
  return <div className="reports-section-picker">{(Object.keys(reportSectionLabels) as ReportSectionKey[]).map((section) => <label key={section}><input type="checkbox" checked={sections.includes(section)} onChange={() => toggle(section)} /> <span>{reportSectionLabels[section]}</span></label>)}</div>;
}

function startDownload(item: ReportExport) {
  const link = document.createElement("a");
  link.href = `/api/v1/reports/exports/${item.id}/download`;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}

export function ReportsPage() {
  const [tab, setTab] = useState<ReportTab>("overview");
  const [range, setRange] = useState<ReportRangeKey>("6m");
  const [saveOpen, setSaveOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [centerOpen, setCenterOpen] = useState(false);
  const [saveName, setSaveName] = useState("6-month financial review");
  const [saveSections, setSaveSections] = useState<ReportSectionKey[]>(["overview"]);
  const [exportName, setExportName] = useState("Budget financial report");
  const [exportRange, setExportRange] = useState<ReportRangeKey>("6m");
  const [exportSections, setExportSections] = useState<ReportSectionKey[]>(["overview", "spending", "budget", "goals"]);
  const queryClient = useQueryClient();
  const days = ranges.find((item) => item.key === range)?.days ?? 184;
  const overview = useQuery({ queryKey: queryKeys.reportsOverview(days), queryFn: () => apiRequest<ReportsOverview>(`/reports/overview?days=${days}`), staleTime: 60_000, enabled: tab === "overview" });
  const spending = useQuery({ queryKey: queryKeys.reportsSpending(range), queryFn: () => apiRequest<ReportsSpending>(`/reports/spending?range=${range}`), staleTime: 60_000, enabled: tab === "spending" });
  const budget = useQuery({ queryKey: queryKeys.reportsBudget(range), queryFn: () => apiRequest<ReportsBudget>(`/reports/budget?range=${range}`), staleTime: 60_000, enabled: tab === "budget" });
  const goalsDebt = useQuery({ queryKey: queryKeys.reportsGoalsDebt(range), queryFn: () => apiRequest<ReportsGoalsDebt>(`/reports/goals-debt?range=${range}`), staleTime: 60_000, enabled: tab === "goals" });
  const saved = useQuery({ queryKey: queryKeys.savedReports, queryFn: () => apiRequest<SavedReportList>("/reports/saved"), staleTime: 30_000 });
  const exports = useQuery({ queryKey: queryKeys.reportExports, queryFn: () => apiRequest<ReportExportList>("/reports/exports?limit=12"), staleTime: 30_000 });
  const activeQuery = tab === "overview" ? overview : tab === "spending" ? spending : tab === "budget" ? budget : goalsDebt;

  const saveReport = useMutation({
    mutationFn: () => apiRequest<SavedReport>("/reports/saved", { method: "POST", body: JSON.stringify({ name: saveName, range, sections: saveSections }) }),
    onSuccess: async () => { setSaveOpen(false); setCenterOpen(true); await queryClient.invalidateQueries({ queryKey: queryKeys.savedReports }); },
  });
  const deleteSaved = useMutation({
    mutationFn: (id: number) => apiRequest<void>(`/reports/saved/${id}`, { method: "DELETE" }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: queryKeys.savedReports }),
  });
  const createExport = useMutation({
    mutationFn: (format: "csv" | "pdf") => apiRequest<ReportExport>("/reports/exports", { method: "POST", body: JSON.stringify({ name: exportName, format, range: exportRange, sections: exportSections }) }),
    onSuccess: async (item) => { startDownload(item); setExportOpen(false); setCenterOpen(true); await queryClient.invalidateQueries({ queryKey: queryKeys.reportExports }); },
  });
  const deleteExport = useMutation({
    mutationFn: (id: number) => apiRequest<void>(`/reports/exports/${id}`, { method: "DELETE" }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: queryKeys.reportExports }),
  });

  const rangeLabel = ranges.find((item) => item.key === range)?.label ?? range;
  const currentSection = tab as ReportSectionKey;
  const openSave = () => {
    setSaveName(`${rangeLabel} ${reportSectionLabels[currentSection]}`);
    setSaveSections([currentSection]);
    setSaveOpen(true);
    setExportOpen(false);
  };
  const openExport = () => {
    setExportName(`Budget ${rangeLabel} report`);
    setExportRange(range);
    setExportSections(["overview", "spending", "budget", "goals"]);
    setExportOpen(true);
    setSaveOpen(false);
  };
  const openSavedReport = (item: SavedReport) => {
    setRange(item.range);
    setTab(reportTabFromSection(item.sections[0] ?? "overview"));
  };
  const submitSave = (event: FormEvent) => { event.preventDefault(); saveReport.mutate(); };

  return (
    <div className="page-container reports-page">
      <PageHeader
        title="Reports"
        description="Historical financial analytics built from Budget's deterministic calculations."
        actions={<div className="reports-header-actions"><Link className="button secondary" to="/advisor" state={{ report: { section: currentSection, range, label: `${rangeLabel} ${reportSectionLabels[currentSection]}` } }}>Ask Budget</Link><button className="button secondary" type="button" onClick={() => setCenterOpen((value) => !value)}>Report center</button><button className="button secondary" type="button" onClick={openSave}>Save view</button><button className="button primary" type="button" onClick={openExport}>Export</button></div>}
      />
      <div className="reports-toolbar">
        <div className="segmented-control reports-tabs" aria-label="Report section">
          <button type="button" className={tab === "overview" ? "active" : ""} onClick={() => setTab("overview")}>Overview</button>
          <button type="button" className={tab === "spending" ? "active" : ""} onClick={() => setTab("spending")}>Spending</button>
          <button type="button" className={tab === "budget" ? "active" : ""} onClick={() => setTab("budget")}>Budget</button>
          <button type="button" className={tab === "goals" ? "active" : ""} onClick={() => setTab("goals")}>Goals &amp; Debt</button>
        </div>
        <div className="segmented-control reports-range-control" aria-label="Report range">{ranges.map((item) => <button type="button" key={item.key} className={range === item.key ? "active" : ""} onClick={() => setRange(item.key)}>{item.label}</button>)}</div>
      </div>

      {saveOpen && <form className="panel reports-config-panel" onSubmit={submitSave}><div><span className="eyebrow">Saved report</span><h2>Save this reporting view</h2><p>Keep a named range and section set so you can reopen the same analysis later.</p></div><label>Report name<input value={saveName} maxLength={120} onChange={(event) => setSaveName(event.target.value)} required /></label><ReportSectionsPicker sections={saveSections} onChange={setSaveSections} />{saveReport.error instanceof Error && <div className="inline-alert" role="alert">{saveReport.error.message}</div>}<div className="reports-config-actions"><button className="button ghost" type="button" onClick={() => setSaveOpen(false)}>Cancel</button><button className="button primary" type="submit" disabled={saveReport.isPending || !saveName.trim() || saveSections.length === 0}>{saveReport.isPending ? "Saving…" : "Save report"}</button></div></form>}

      {exportOpen && <section className="panel reports-config-panel"><div><span className="eyebrow">Export</span><h2>Build a reproducible report</h2><p>Choose the range and sections. Budget stores the deterministic report snapshot and generated file so this exact export remains available later.</p></div><label>Export name<input value={exportName} maxLength={120} onChange={(event) => setExportName(event.target.value)} /></label><label>Range<select value={exportRange} onChange={(event) => setExportRange(event.target.value as ReportRangeKey)}>{ranges.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}</select></label><ReportSectionsPicker sections={exportSections} onChange={setExportSections} />{createExport.error instanceof Error && <div className="inline-alert" role="alert">{createExport.error.message}</div>}<div className="reports-config-actions"><button className="button ghost" type="button" onClick={() => setExportOpen(false)}>Cancel</button><button className="button secondary" type="button" disabled={createExport.isPending || !exportName.trim() || exportSections.length === 0} onClick={() => createExport.mutate("csv")}>CSV</button><button className="button primary" type="button" disabled={createExport.isPending || !exportName.trim() || exportSections.length === 0} onClick={() => createExport.mutate("pdf")}>{createExport.isPending ? "Building…" : "PDF report"}</button></div></section>}

      {centerOpen && <section className="panel reports-center"><div className="reports-section-heading"><div><span className="eyebrow">Report center</span><h2>Saved reports &amp; export history</h2></div><span className="reports-range">Reopen or reproduce</span></div><div className="reports-center-grid"><div><h3>Saved reports</h3>{saved.isPending ? <p className="muted-copy">Loading saved reports…</p> : saved.data?.reports.length ? <div className="reports-saved-list">{saved.data.reports.map((item) => <article key={item.id}><button type="button" className="reports-saved-open" onClick={() => openSavedReport(item)}><strong>{item.name}</strong><span>{ranges.find((rangeItem) => rangeItem.key === item.range)?.label} · {item.sections.map((section) => reportSectionLabels[section]).join(", ")}</span></button><button type="button" className="text-button" disabled={deleteSaved.isPending} onClick={() => { if (window.confirm(`Delete saved report “${item.name}”?`)) deleteSaved.mutate(item.id); }}>Delete</button></article>)}</div> : <p className="muted-copy">No saved reports yet.</p>}</div><div><h3>Recent exports</h3>{exports.isPending ? <p className="muted-copy">Loading exports…</p> : exports.data?.exports.length ? <div className="reports-export-list">{exports.data.exports.map((item) => <article key={item.id}><div><strong>{item.name}</strong><span>{item.format.toUpperCase()} · {new Date(item.created_at).toLocaleString()} · {(item.file_size / 1024).toFixed(1)} KB</span></div><div><a className="text-link" href={`/api/v1/reports/exports/${item.id}/download`} download>Download</a><button type="button" className="text-button" disabled={deleteExport.isPending} onClick={() => deleteExport.mutate(item.id)}>Remove</button></div></article>)}</div> : <p className="muted-copy">Exports you create will appear here.</p>}</div></div></section>}

      {activeQuery.isPending && <LoadingState label="Building your financial report" />}
      {activeQuery.isError && <ErrorState message="Reports could not be loaded." onRetry={() => void activeQuery.refetch()} />}
      {tab === "overview" && overview.data && <OverviewReport data={overview.data} days={days} />}
      {tab === "spending" && spending.data && <SpendingReport data={spending.data} />}
      {tab === "budget" && budget.data && <BudgetReport data={budget.data} />}
      {tab === "goals" && goalsDebt.data && <GoalsDebtReport data={goalsDebt.data} />}
    </div>
  );
}
