import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type {
  AccountsResponse,
  DebtItem,
  DebtStrategy,
  DebtType,
  DebtWrite,
  DebtsResponse,
  FinancialGoal,
  FinancialGoalsResponse,
  FinancialGoalWrite,
  ForecastResponse,
  ForecastScenarioResponse,
  GoalType,
} from "../api/types";
import { Amount } from "../components/Amount";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { PageHeader } from "../components/PageHeader";
import { formatDate, formatMoney, formatPercent, numberFromMoney } from "../lib/format";

type Tab = "goals" | "debt" | "forecast" | "scenario";

const GOAL_TYPES: Array<{ value: GoalType; label: string }> = [
  { value: "emergency_fund", label: "Emergency fund" },
  { value: "savings", label: "Savings" },
  { value: "down_payment", label: "Down payment" },
  { value: "vacation", label: "Vacation" },
  { value: "purchase", label: "Large purchase" },
  { value: "custom", label: "Custom" },
];

const DEBT_TYPES: Array<{ value: DebtType; label: string }> = [
  { value: "credit_card", label: "Credit card" },
  { value: "auto", label: "Auto loan" },
  { value: "student", label: "Student loan" },
  { value: "personal", label: "Personal loan" },
  { value: "mortgage", label: "Mortgage" },
  { value: "medical", label: "Medical" },
  { value: "other", label: "Other" },
];

function dateOrDash(value: string | null): string {
  return value ? formatDate(value, true) : "—";
}

function GoalEditor({ accounts, goal, onDone }: { accounts: AccountsResponse; goal?: FinancialGoal; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(goal?.name ?? "");
  const [goalType, setGoalType] = useState<GoalType>(goal?.goal_type ?? "savings");
  const [target, setTarget] = useState(goal?.target_amount ?? "");
  const [current, setCurrent] = useState(goal?.current_amount ?? "0");
  const [monthly, setMonthly] = useState(goal?.monthly_contribution ?? "0");
  const [targetDate, setTargetDate] = useState(goal?.target_date ?? "");
  const [accountId, setAccountId] = useState(goal?.linked_account?.id ? String(goal.linked_account.id) : "");
  const [notes, setNotes] = useState(goal?.notes ?? "");

  const mutation = useMutation({
    mutationFn: (payload: FinancialGoalWrite) => apiRequest<FinancialGoalsResponse>(goal ? `/planning/goals/${goal.id}` : "/planning/goals", {
      method: goal ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    }),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.goals, data);
      void queryClient.invalidateQueries({ queryKey: queryKeys.forecast });
      onDone();
    },
  });

  const save = () => mutation.mutate({
    name: name.trim(),
    goal_type: goalType,
    target_amount: target || "0",
    current_amount: current || "0",
    monthly_contribution: monthly || "0",
    target_date: targetDate || null,
    linked_account_id: accountId ? Number(accountId) : null,
    priority: goal?.priority ?? 100,
    active: goal?.active ?? true,
    notes: notes.trim() || null,
  });

  return (
    <section className="panel plan-editor">
      <div className="panel-heading"><div><span className="eyebrow">{goal ? "Edit goal" : "New goal"}</span><h2>{goal ? goal.name : "Create a financial goal"}</h2></div><button className="button ghost" type="button" onClick={onDone}>Close</button></div>
      <div className="form-grid two-columns">
        <label>Name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="Emergency fund" /></label>
        <label>Type<select value={goalType} onChange={(event) => setGoalType(event.target.value as GoalType)}>{GOAL_TYPES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
        <label>Target amount<input inputMode="decimal" value={target} onChange={(event) => setTarget(event.target.value)} placeholder="12000" /></label>
        <label>Current amount<input inputMode="decimal" value={current} disabled={Boolean(accountId)} onChange={(event) => setCurrent(event.target.value)} /></label>
        <label>Monthly contribution<input inputMode="decimal" value={monthly} onChange={(event) => setMonthly(event.target.value)} placeholder="500" /></label>
        <label>Target date <span className="optional">Optional</span><input type="date" value={targetDate} onChange={(event) => setTargetDate(event.target.value)} /></label>
        <label>Track account <span className="optional">Optional</span><select value={accountId} onChange={(event) => setAccountId(event.target.value)}><option value="">Manual balance</option>{accounts.accounts.filter((account) => ["depository", "investment"].includes(account.account_type)).map((account) => <option key={account.id} value={account.id}>{account.display_name}</option>)}</select></label>
        <label>Notes <span className="optional">Optional</span><input value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
      </div>
      {mutation.isError && <div className="inline-alert" role="alert">{mutation.error.message}</div>}
      <div className="form-actions"><button className="button primary" type="button" disabled={mutation.isPending || !name.trim() || numberFromMoney(target) <= 0} onClick={save}>{mutation.isPending ? "Saving…" : "Save goal"}</button></div>
    </section>
  );
}

function GoalsTab({ data, accounts }: { data: FinancialGoalsResponse; accounts: AccountsResponse }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<FinancialGoal | "new" | null>(null);
  const contribution = useMutation({
    mutationFn: ({ id, amount }: { id: number; amount: string }) => apiRequest<FinancialGoalsResponse>(`/planning/goals/${id}/contributions`, {
      method: "POST",
      body: JSON.stringify({ amount, contribution_date: new Date().toISOString().slice(0, 10), notes: null }),
    }),
    onSuccess: (next) => {
      queryClient.setQueryData(queryKeys.goals, next);
      void queryClient.invalidateQueries({ queryKey: queryKeys.forecast });
    },
  });
  const remove = useMutation({
    mutationFn: (id: number) => apiRequest<{ ok: boolean }>(`/planning/goals/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.goals });
      void queryClient.invalidateQueries({ queryKey: queryKeys.forecast });
    },
  });

  return <>
    <div className="metric-grid planning-metrics">
      <article className="metric-card featured"><span>Goal progress</span><strong>{formatMoney(data.total_current, data.currency)}</strong><small>of {formatMoney(data.total_target, data.currency)}</small></article>
      <article className="metric-card"><span>Monthly contributions</span><strong>{formatMoney(data.monthly_contributions, data.currency)}</strong><small>across active goals</small></article>
      <article className="metric-card"><span>Active goals</span><strong>{data.goals.filter((goal) => goal.active).length}</strong><small>{data.goals.length} total</small></article>
    </div>
    <div className="planning-action-row"><button className="button primary" type="button" onClick={() => setEditing("new")}>Add goal</button></div>
    {editing && <GoalEditor accounts={accounts} goal={editing === "new" ? undefined : editing} onDone={() => setEditing(null)} />}
    <section className="planning-card-grid">
      {data.goals.length === 0 && <EmptyState title="No goals yet" message="Add an emergency fund, savings target, down payment, or anything else you want to work toward." />}
      {data.goals.map((goal) => <article className="panel goal-card" key={goal.id}>
        <div className="goal-card-heading"><div><span className="eyebrow">{GOAL_TYPES.find((item) => item.value === goal.goal_type)?.label}</span><h2>{goal.name}</h2></div><strong>{formatPercent(goal.progress_pct)}</strong></div>
        <div className="goal-progress"><span style={{ width: `${Math.min(numberFromMoney(goal.progress_pct), 100)}%` }} /></div>
        <div className="planning-stat-pair"><div><span>Current</span><strong>{formatMoney(goal.current_amount, data.currency)}</strong></div><div><span>Target</span><strong>{formatMoney(goal.target_amount, data.currency)}</strong></div></div>
        <p className="planning-muted">{formatMoney(goal.remaining_amount, data.currency)} remaining · {formatMoney(goal.monthly_contribution, data.currency)}/month · projected {dateOrDash(goal.projected_date)}</p>
        {goal.linked_account && <p className="planning-linked">Tracking {goal.linked_account.display_name}</p>}
        <div className="card-actions">
          {!goal.linked_account && <button className="button ghost" type="button" onClick={() => { const amount = window.prompt("Contribution amount"); if (amount && numberFromMoney(amount) > 0) contribution.mutate({ id: goal.id, amount }); }}>Add contribution</button>}
          <button className="button ghost" type="button" onClick={() => setEditing(goal)}>Edit</button>
          <button className="button danger" type="button" onClick={() => { if (window.confirm(`Delete ${goal.name}?`)) remove.mutate(goal.id); }}>Delete</button>
        </div>
      </article>)}
    </section>
  </>;
}

function DebtEditor({ accounts, debt, onDone }: { accounts: AccountsResponse; debt?: DebtItem; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(debt?.name ?? "");
  const [type, setType] = useState<DebtType>(debt?.debt_type ?? "other");
  const [balance, setBalance] = useState(debt?.balance ?? "");
  const [apr, setApr] = useState(debt?.apr ?? "0");
  const [minimum, setMinimum] = useState(debt?.minimum_payment ?? "0");
  const [extra, setExtra] = useState(debt?.extra_payment ?? "0");
  const [accountId, setAccountId] = useState(debt?.linked_account?.id ? String(debt.linked_account.id) : "");
  const [dueDay, setDueDay] = useState(debt?.due_day ? String(debt.due_day) : "");
  const [notes, setNotes] = useState(debt?.notes ?? "");
  const mutation = useMutation({
    mutationFn: (payload: DebtWrite) => apiRequest<DebtsResponse>(debt ? `/planning/debts/${debt.id}` : "/planning/debts", { method: debt ? "PATCH" : "POST", body: JSON.stringify(payload) }),
    onSuccess: (data) => { queryClient.setQueryData(queryKeys.debts, data); void queryClient.invalidateQueries({ queryKey: queryKeys.forecast }); onDone(); },
  });
  const save = () => mutation.mutate({
    name: name.trim(), debt_type: type, balance: balance || "0", apr: apr || "0", minimum_payment: minimum || "0", extra_payment: extra || "0", linked_account_id: accountId ? Number(accountId) : null, strategy_priority: debt?.strategy_priority ?? 100, due_day: dueDay ? Number(dueDay) : null, active: debt?.active ?? true, notes: notes.trim() || null,
  });
  return <section className="panel plan-editor"><div className="panel-heading"><div><span className="eyebrow">{debt ? "Edit debt" : "New debt"}</span><h2>{debt ? debt.name : "Add a debt"}</h2></div><button className="button ghost" type="button" onClick={onDone}>Close</button></div><div className="form-grid two-columns">
    <label>Name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="Auto loan" /></label>
    <label>Type<select value={type} onChange={(event) => setType(event.target.value as DebtType)}>{DEBT_TYPES.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label>
    <label>Balance<input inputMode="decimal" value={balance} disabled={Boolean(accountId)} onChange={(event) => setBalance(event.target.value)} /></label>
    <label>APR %<input inputMode="decimal" value={apr} onChange={(event) => setApr(event.target.value)} /></label>
    <label>Minimum payment<input inputMode="decimal" value={minimum} onChange={(event) => setMinimum(event.target.value)} /></label>
    <label>Extra payment<input inputMode="decimal" value={extra} onChange={(event) => setExtra(event.target.value)} /></label>
    <label>Track account <span className="optional">Optional</span><select value={accountId} onChange={(event) => setAccountId(event.target.value)}><option value="">Manual balance</option>{accounts.accounts.filter((account) => ["credit", "loan"].includes(account.account_type)).map((account) => <option key={account.id} value={account.id}>{account.display_name}</option>)}</select></label>
    <label>Due day <span className="optional">Optional</span><input type="number" min="1" max="31" value={dueDay} onChange={(event) => setDueDay(event.target.value)} /></label>
    <label className="full-width">Notes <span className="optional">Optional</span><input value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
  </div>{mutation.isError && <div className="inline-alert" role="alert">{mutation.error.message}</div>}<div className="form-actions"><button className="button primary" type="button" disabled={mutation.isPending || !name.trim()} onClick={save}>{mutation.isPending ? "Saving…" : "Save debt"}</button></div></section>;
}

function DebtsTab({ data, accounts }: { data: DebtsResponse; accounts: AccountsResponse }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState<DebtItem | "new" | null>(null);
  const [strategy, setStrategy] = useState<DebtStrategy>(data.strategy);
  const [extraBudget, setExtraBudget] = useState(data.monthly_extra_budget);
  const strategyMutation = useMutation({ mutationFn: () => apiRequest<DebtsResponse>("/planning/debts/strategy", { method: "PUT", body: JSON.stringify({ strategy, monthly_extra_budget: extraBudget || "0" }) }), onSuccess: (next) => { queryClient.setQueryData(queryKeys.debts, next); void queryClient.invalidateQueries({ queryKey: queryKeys.forecast }); } });
  const remove = useMutation({ mutationFn: (id: number) => apiRequest<{ ok: boolean }>(`/planning/debts/${id}`, { method: "DELETE" }), onSuccess: () => { void queryClient.invalidateQueries({ queryKey: queryKeys.debts }); void queryClient.invalidateQueries({ queryKey: queryKeys.forecast }); } });
  return <>
    <div className="metric-grid planning-metrics"><article className="metric-card featured"><span>Total debt</span><strong>{formatMoney(data.total_balance, data.currency)}</strong><small>{formatMoney(data.planned_monthly_payment, data.currency)}/month planned</small></article><article className="metric-card"><span>Debt-free date</span><strong>{dateOrDash(data.planned_debt_free_date)}</strong><small>minimum-only: {dateOrDash(data.minimum_debt_free_date)}</small></article><article className="metric-card"><span>Interest saved</span><strong>{formatMoney(data.interest_saved, data.currency)}</strong><small>vs. minimum payments</small></article></div>
    <section className="panel strategy-panel"><div><span className="eyebrow">Payoff strategy</span><h2>Choose where extra money goes</h2><p>Avalanche prioritizes APR, snowball prioritizes balance, and custom uses your priority order.</p></div><label>Strategy<select value={strategy} onChange={(event) => setStrategy(event.target.value as DebtStrategy)}><option value="avalanche">Avalanche</option><option value="snowball">Snowball</option><option value="custom">Custom</option></select></label><label>Extra monthly pool<input inputMode="decimal" value={extraBudget} onChange={(event) => setExtraBudget(event.target.value)} /></label><button className="button primary" type="button" onClick={() => strategyMutation.mutate()} disabled={strategyMutation.isPending}>Apply strategy</button></section>
    <div className="planning-action-row"><button className="button primary" type="button" onClick={() => setEditing("new")}>Add debt</button></div>
    {editing && <DebtEditor accounts={accounts} debt={editing === "new" ? undefined : editing} onDone={() => setEditing(null)} />}
    <section className="planning-card-grid">{data.debts.length === 0 && <EmptyState title="No debts added" message="Add loans or cards to compare payoff strategies and forecast their effect." />}{data.debts.map((debt) => <article className="panel debt-card" key={debt.id}><div className="goal-card-heading"><div><span className="eyebrow">{DEBT_TYPES.find((item) => item.value === debt.debt_type)?.label}</span><h2>{debt.name}</h2></div><strong>{formatMoney(debt.balance, data.currency)}</strong></div><div className="planning-stat-pair"><div><span>APR</span><strong>{numberFromMoney(debt.apr).toFixed(2)}%</strong></div><div><span>Payment</span><strong>{formatMoney(numberFromMoney(debt.minimum_payment) + numberFromMoney(debt.extra_payment), data.currency)}</strong></div></div><p className="planning-muted">Planned payoff {dateOrDash(debt.planned_payoff_date)} · {formatMoney(debt.interest_saved, data.currency)} interest saved</p>{debt.linked_account && <p className="planning-linked">Balance from {debt.linked_account.display_name}</p>}<div className="card-actions"><button className="button ghost" type="button" onClick={() => setEditing(debt)}>Edit</button><button className="button danger" type="button" onClick={() => { if (window.confirm(`Delete ${debt.name}?`)) remove.mutate(debt.id); }}>Delete</button></div></article>)}</section>
  </>;
}

function ForecastTab({ data }: { data: ForecastResponse }) {
  const queryClient = useQueryClient();
  const [reserve, setReserve] = useState(data.reserve_balance);
  const [includeBudget, setIncludeBudget] = useState(data.include_budget_reserve);
  const mutation = useMutation({ mutationFn: () => apiRequest<ForecastResponse>("/planning/forecast/assumptions", { method: "PUT", body: JSON.stringify({ reserve_balance: reserve || "0", include_budget_reserve: includeBudget }) }), onSuccess: (next) => queryClient.setQueryData(queryKeys.forecast, next) });
  return <>
    <section className="panel forecast-settings"><div><span className="eyebrow">Forecast assumptions</span><h2>Protect a cash floor</h2><p>Budget reserve keeps planned spending in the projection instead of pretending every unspent dollar is free.</p></div><label>Reserve balance<input inputMode="decimal" value={reserve} onChange={(event) => setReserve(event.target.value)} /></label><label className="checkbox-row"><input type="checkbox" checked={includeBudget} onChange={(event) => setIncludeBudget(event.target.checked)} /> Include budget reserve</label><button className="button primary" type="button" onClick={() => mutation.mutate()}>Save</button></section>
    <div className="forecast-horizon-grid">{data.horizons.map((row) => <article className="panel forecast-card" key={row.days}><span className="eyebrow">{row.days} days · {formatDate(row.date, true)}</span><h2>{formatMoney(row.projected_balance, data.currency)}</h2><p className={numberFromMoney(row.above_reserve) >= 0 ? "positive" : "negative"}>{formatMoney(row.above_reserve, data.currency, { showSign: true })} above reserve</p><dl><div><dt>Income</dt><dd>{formatMoney(row.income, data.currency)}</dd></div><div><dt>Recurring bills</dt><dd>{formatMoney(row.recurring_expenses, data.currency)}</dd></div><div><dt>Budget reserve</dt><dd>{formatMoney(row.budget_reserve, data.currency)}</dd></div><div><dt>Debt</dt><dd>{formatMoney(row.debt_payments, data.currency)}</dd></div><div><dt>Goals</dt><dd>{formatMoney(row.goal_contributions, data.currency)}</dd></div></dl></article>)}</div>
    <section className="panel upcoming-panel"><div className="panel-heading"><div><span className="eyebrow">Next 45 days</span><h2>Upcoming recurring activity</h2><p className="planning-muted">Gross cash {formatMoney(data.cash_available, data.currency)} · linked goal reserves {formatMoney(data.goal_reserves, data.currency)}</p></div><strong>{formatMoney(data.spendable_cash, data.currency)}</strong></div>{data.upcoming.length === 0 ? <EmptyState title="No recurring activity detected" message="Sync more history or rebuild Recurring so Forecast has a schedule to work with." /> : <div className="upcoming-list">{data.upcoming.map((item, index) => <div key={`${item.date}-${item.name}-${index}`}><span>{formatDate(item.date)}</span><strong>{item.name}</strong><Amount value={item.kind === "expense" ? `-${item.amount}` : item.amount} currency={data.currency} /></div>)}</div>}</section>
  </>;
}

function ScenarioTab({ currency }: { currency: string }) {
  const [extraDebt, setExtraDebt] = useState("0");
  const [goalAdjustment, setGoalAdjustment] = useState("0");
  const [spendingReduction, setSpendingReduction] = useState("0");
  const [newExpense, setNewExpense] = useState("0");
  const mutation = useMutation({ mutationFn: () => apiRequest<ForecastScenarioResponse>("/planning/forecast/scenario", { method: "POST", body: JSON.stringify({ extra_debt_payment: extraDebt || "0", goal_contribution_adjustment: goalAdjustment || "0", spending_reduction: spendingReduction || "0", new_monthly_expense: newExpense || "0" }) }) });
  const result = mutation.data;
  return <><section className="panel scenario-builder"><div><span className="eyebrow">What if?</span><h2>Test a plan without changing your real budget</h2><p>Scenario mode is read-only. Nothing here changes goals, debts, or allocations.</p></div><div className="form-grid two-columns"><label>Extra debt payment / month<input inputMode="decimal" value={extraDebt} onChange={(event) => setExtraDebt(event.target.value)} /></label><label>Goal contribution change / month<input inputMode="decimal" value={goalAdjustment} onChange={(event) => setGoalAdjustment(event.target.value)} /></label><label>Reduce spending / month<input inputMode="decimal" value={spendingReduction} onChange={(event) => setSpendingReduction(event.target.value)} /></label><label>Add new expense / month<input inputMode="decimal" value={newExpense} onChange={(event) => setNewExpense(event.target.value)} /></label></div><button className="button primary" type="button" onClick={() => mutation.mutate()} disabled={mutation.isPending}>{mutation.isPending ? "Running…" : "Run scenario"}</button></section>{result && <section className="scenario-results"><article className="panel"><span className="eyebrow">90-day cash impact</span><h2>{formatMoney(result.cash_impact_90_days, currency, { showSign: true })}</h2><p>Scenario balance {formatMoney(result.scenario.horizons.at(-1)?.projected_balance ?? "0", currency)} vs. baseline {formatMoney(result.baseline.horizons.at(-1)?.projected_balance ?? "0", currency)}.</p></article><article className="panel"><span className="eyebrow">Debt impact</span><h2>{formatMoney(result.interest_saved, currency)} saved</h2><p>Debt-free {dateOrDash(result.scenario_debt_free_date)} vs. baseline {dateOrDash(result.baseline_debt_free_date)}.</p></article></section>}</>;
}

export function PlanPage() {
  const [tab, setTab] = useState<Tab>("goals");
  const goals = useQuery({ queryKey: queryKeys.goals, queryFn: () => apiRequest<FinancialGoalsResponse>("/planning/goals") });
  const debts = useQuery({ queryKey: queryKeys.debts, queryFn: () => apiRequest<DebtsResponse>("/planning/debts") });
  const forecast = useQuery({ queryKey: queryKeys.forecast, queryFn: () => apiRequest<ForecastResponse>("/planning/forecast") });
  const accounts = useQuery({ queryKey: queryKeys.accounts, queryFn: () => apiRequest<AccountsResponse>("/accounts") });
  const busy = goals.isPending || debts.isPending || forecast.isPending || accounts.isPending;
  const failed = goals.isError || debts.isError || forecast.isError || accounts.isError;
  const actions = useMemo(() => <div className="segmented-control plan-tabs">{(["goals", "debt", "forecast", "scenario"] as Tab[]).map((item) => <button type="button" key={item} className={tab === item ? "active" : ""} onClick={() => setTab(item)}>{item === "debt" ? "Debt" : item[0].toUpperCase() + item.slice(1)}</button>)}</div>, [tab]);
  const currency = goals.data?.currency ?? debts.data?.currency ?? forecast.data?.currency ?? "USD";
  return <div className="page-container plan-page"><PageHeader title="Plan" description="Goals, debt payoff, and forward-looking cash planning." actions={actions} />{busy && <LoadingState label="Building your financial plan" />}{failed && <ErrorState message="Your planning data could not be loaded." onRetry={() => { void goals.refetch(); void debts.refetch(); void forecast.refetch(); void accounts.refetch(); }} />}{!busy && !failed && accounts.data && goals.data && debts.data && forecast.data && <>{tab === "goals" && <GoalsTab data={goals.data} accounts={accounts.data} />}{tab === "debt" && <DebtsTab data={debts.data} accounts={accounts.data} />}{tab === "forecast" && <ForecastTab data={forecast.data} />}{tab === "scenario" && <ScenarioTab currency={currency} />}</>}</div>;
}
