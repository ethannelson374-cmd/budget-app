import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type {
  AnnualBudgetPlan,
  AnnualBudgetPlanWrite,
  BudgetDistribution,
  CategorySelection,
  MonthlyBudgetMode,
  MonthlyBudgetView,
  MonthlyBudgetWrite,
  RolloverMode,
  YearBudgetView,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Amount } from "../components/Amount";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { PageHeader } from "../components/PageHeader";
import { MoneyInput } from "../components/MoneyInput";
import { currentMonth, formatMoney, formatMoneyInput, monthLabel, numberFromMoney } from "../lib/format";

const MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const ROLLOVER_OPTIONS: Array<{ value: RolloverMode; label: string }> = [
  { value: "off", label: "No rollover" },
  { value: "surplus", label: "Carry surplus" },
  { value: "surplus_and_deficit", label: "Carry surplus + deficit" },
];

function shiftMonth(month: string, delta: number): string {
  const [year, monthNumber] = month.split("-").map(Number);
  const result = new Date(year, monthNumber - 1 + delta, 1);
  return `${result.getFullYear()}-${String(result.getMonth() + 1).padStart(2, "0")}`;
}

function expenseCategories(categories: CategorySelection) {
  return categories.categories.filter((category) => category.enabled && !["income", "transfers"].includes(category.key));
}

type AnnualDraft = Record<number, {
  annualAmount: string;
  distribution: BudgetDistribution;
  monthlyAmount: string;
  rolloverMode: RolloverMode;
  customMonths: string[];
}>;

function annualDraft(plan: AnnualBudgetPlan, categories: CategorySelection): AnnualDraft {
  const existing = new Map(plan.categories.map((item) => [item.category.id, item]));
  return Object.fromEntries(expenseCategories(categories).map((category) => {
    const row = existing.get(category.id);
    return [category.id, {
      annualAmount: row?.annual_amount ?? "0",
      distribution: row?.distribution ?? "even",
      monthlyAmount: row?.monthly_amount ?? "0",
      rolloverMode: row?.rollover_mode ?? "off",
      customMonths: Array.from({ length: 12 }, (_, index) => row?.custom_months.find((item) => item.month === index + 1)?.amount ?? "0"),
    }];
  }));
}

function AnnualPlanEditor({ year, plan, categories, onClose }: { year: number; plan: AnnualBudgetPlan; categories: CategorySelection; onClose: () => void }) {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [plannedIncome, setPlannedIncome] = useState(plan.planned_income === "0.0000" && !plan.exists ? "" : plan.planned_income);
  const [notes, setNotes] = useState(plan.notes ?? "");
  const [draft, setDraft] = useState<AnnualDraft>(() => annualDraft(plan, categories));
  const mutation = useMutation({
    mutationFn: (payload: AnnualBudgetPlanWrite) => apiRequest<AnnualBudgetPlan>(`/budget/years/${year}/plan`, { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.annualBudgetPlan(year), saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.budgetYear(year) });
      void queryClient.invalidateQueries({ queryKey: ["budget-month"] });
      onClose();
    },
  });

  const update = (categoryId: number, patch: Partial<AnnualDraft[number]>) => setDraft((current) => ({ ...current, [categoryId]: { ...current[categoryId], ...patch } }));
  const save = () => {
    const categoriesPayload = expenseCategories(categories).flatMap((category) => {
      const row = draft[category.id];
      const effectiveAnnual = row.distribution === "monthly"
        ? numberFromMoney(row.monthlyAmount) * 12
        : row.distribution === "custom"
          ? row.customMonths.reduce((sum, value) => sum + numberFromMoney(value), 0)
          : numberFromMoney(row.annualAmount);
      if (effectiveAnnual <= 0) return [];
      return [{
        category_id: category.id,
        annual_amount: row.annualAmount || "0",
        distribution: row.distribution,
        monthly_amount: row.distribution === "monthly" ? row.monthlyAmount || "0" : null,
        custom_months: row.distribution === "custom" ? row.customMonths.map((amount, index) => ({ month: index + 1, amount: amount || "0" })) : [],
        rollover_mode: row.rolloverMode,
      }];
    });
    mutation.mutate({ planned_income: plannedIncome || "0", notes: notes.trim() || null, categories: categoriesPayload });
  };
  const error = mutation.error instanceof ApiError ? mutation.error.message : null;

  return (
    <section className="panel budget-editor">
      <div className="panel-heading"><div><span className="eyebrow">Annual plan</span><h2>{year} budget goals</h2><p>Set the year once, then override only the months that are unusual.</p></div><button className="button ghost" type="button" onClick={onClose}>Close</button></div>
      {error && <div className="inline-alert" role="alert">{error}</div>}
      <div className="form-grid two-columns budget-income-grid">
        <label>Planned annual take-home income<MoneyInput value={plannedIncome} onValueChange={setPlannedIncome} placeholder={user?.settings.annual_gross_income ? `Gross income on profile: ${formatMoneyInput(user.settings.annual_gross_income)}` : "78,000.00"} /></label>
        <label>Notes <span className="optional">Optional</span><input value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Base plan for the year" /></label>
      </div>
      <div className="annual-budget-editor-list">
        {expenseCategories(categories).map((category) => {
          const row = draft[category.id];
          return (
            <article className="annual-budget-editor-row" key={category.id}>
              <div className="budget-category-title"><strong>{category.name}</strong><span>{category.group}</span></div>
              <label>Distribution<select value={row.distribution} onChange={(event) => update(category.id, { distribution: event.target.value as BudgetDistribution })}><option value="even">Annual goal ÷ 12</option><option value="monthly">Same monthly amount</option><option value="custom">Custom by month</option></select></label>
              {row.distribution === "even" && <label>Annual goal<MoneyInput value={row.annualAmount} onValueChange={(annualAmount) => update(category.id, { annualAmount })} /></label>}
              {row.distribution === "monthly" && <label>Monthly amount<MoneyInput value={row.monthlyAmount} onValueChange={(monthlyAmount) => update(category.id, { monthlyAmount })} /></label>}
              <label>Rollover<select value={row.rolloverMode} onChange={(event) => update(category.id, { rolloverMode: event.target.value as RolloverMode })}>{ROLLOVER_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
              {row.distribution === "custom" && <div className="custom-month-grid">{MONTH_NAMES.map((name, index) => <label key={name}>{name}<MoneyInput value={row.customMonths[index]} onValueChange={(amount) => { const months = [...row.customMonths]; months[index] = amount; update(category.id, { customMonths: months }); }} /></label>)}</div>}
            </article>
          );
        })}
      </div>
      <div className="form-actions end"><button className="button primary" type="button" disabled={mutation.isPending} onClick={save}>{mutation.isPending ? "Saving…" : `Save ${year} plan`}</button></div>
    </section>
  );
}

function MonthlyEditor({ month, budget, categories, onClose }: { month: string; budget: MonthlyBudgetView; categories: CategorySelection; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<MonthlyBudgetMode>(budget.has_annual_plan ? "override" : "standalone");
  const [plannedIncome, setPlannedIncome] = useState(budget.planned_income);
  const [notes, setNotes] = useState(budget.notes ?? "");
  const byId = new Map(budget.categories.map((row) => [row.category.id, row]));
  const [amounts, setAmounts] = useState<Record<number, string>>(() => Object.fromEntries(expenseCategories(categories).map((category) => [category.id, byId.get(category.id)?.base_amount ?? "0"])));
  const [rollovers, setRollovers] = useState<Record<number, RolloverMode>>(() => Object.fromEntries(expenseCategories(categories).map((category) => [category.id, byId.get(category.id)?.rollover_mode ?? "off"])));
  const mutation = useMutation({
    mutationFn: (payload: MonthlyBudgetWrite) => apiRequest<MonthlyBudgetView>(`/budget/months/${month}`, { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.budgetMonth(month), saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.budgetYear(Number(month.slice(0, 4))) });
      onClose();
    },
  });
  const save = () => mutation.mutate({
    mode,
    planned_income: plannedIncome || null,
    notes: notes.trim() || null,
    categories: expenseCategories(categories).flatMap((category) => {
      const amount = amounts[category.id] || "0";
      if (mode === "standalone" && numberFromMoney(amount) <= 0) return [];
      return [{ category_id: category.id, planned_amount: amount, rollover_mode: rollovers[category.id] ?? "off" }];
    }),
  });
  const error = mutation.error instanceof ApiError ? mutation.error.message : null;
  return (
    <section className="panel budget-editor">
      <div className="panel-heading"><div><span className="eyebrow">Monthly plan</span><h2>Edit {monthLabel(month)}</h2><p>{budget.has_annual_plan ? "Override this month without changing the rest of the year, or make it standalone." : "Set a standalone budget for this month."}</p></div><button className="button ghost" type="button" onClick={onClose}>Close</button></div>
      {error && <div className="inline-alert" role="alert">{error}</div>}
      <div className="form-grid two-columns">
        {budget.has_annual_plan && <label>Planning mode<select value={mode} onChange={(event) => setMode(event.target.value as MonthlyBudgetMode)}><option value="override">Override annual plan for this month</option><option value="standalone">Standalone monthly budget</option></select></label>}
        <label>Planned income<MoneyInput value={plannedIncome} onValueChange={setPlannedIncome} /></label>
        <label className="budget-notes-field">Notes <span className="optional">Optional</span><input value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
      </div>
      <div className="monthly-budget-editor-list">
        {expenseCategories(categories).map((category) => <div className="monthly-budget-editor-row" key={category.id}><div><strong>{category.name}</strong><span>{category.group}</span></div><label>Planned<MoneyInput value={amounts[category.id] ?? "0"} onValueChange={(amount) => setAmounts((current) => ({ ...current, [category.id]: amount }))} /></label><label>Rollover<select value={rollovers[category.id] ?? "off"} onChange={(event) => setRollovers((current) => ({ ...current, [category.id]: event.target.value as RolloverMode }))}>{ROLLOVER_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label></div>)}
      </div>
      <div className="form-actions end"><button className="button primary" type="button" disabled={mutation.isPending} onClick={save}>{mutation.isPending ? "Saving…" : "Save month"}</button></div>
    </section>
  );
}

function MonthBudget({ month, budget, categories }: { month: string; budget: MonthlyBudgetView; categories: CategorySelection }) {
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const copyPrevious = useMutation({
    mutationFn: () => apiRequest<MonthlyBudgetView>(`/budget/months/${month}/copy-previous`, { method: "POST" }),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.budgetMonth(month), saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.budgetYear(Number(month.slice(0, 4))) });
    },
  });
  const clearMonth = useMutation({
    mutationFn: () => apiRequest<MonthlyBudgetView>(`/budget/months/${month}`, { method: "DELETE" }),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.budgetMonth(month), saved);
      void queryClient.invalidateQueries({ queryKey: queryKeys.budgetYear(Number(month.slice(0, 4))) });
    },
  });
  if (editing) return <MonthlyEditor month={month} budget={budget} categories={categories} onClose={() => setEditing(false)} />;
  const sourceLabel = budget.source === "annual" ? "Annual plan" : budget.source === "override" ? "Annual plan + month override" : budget.source === "standalone" ? "Standalone month" : "No plan yet";
  return (
    <>
      <div className="budget-toolbar"><span className="budget-source-badge">{sourceLabel}</span><div>{["override", "standalone"].includes(budget.source) && <button className="button ghost" type="button" disabled={clearMonth.isPending} onClick={() => { if (window.confirm(budget.has_annual_plan ? "Use the annual plan for this month again?" : "Clear this monthly budget?")) clearMonth.mutate(); }}>{clearMonth.isPending ? "Clearing…" : budget.has_annual_plan ? "Use annual plan" : "Clear month"}</button>}<button className="button secondary" type="button" disabled={copyPrevious.isPending} onClick={() => copyPrevious.mutate()}>{copyPrevious.isPending ? "Copying…" : "Copy previous month"}</button><button className="button primary" type="button" onClick={() => setEditing(true)}>Edit month</button></div></div>
      {(copyPrevious.isError || clearMonth.isError) && <div className="inline-alert" role="alert">{copyPrevious.error instanceof ApiError ? copyPrevious.error.message : clearMonth.error instanceof ApiError ? clearMonth.error.message : "The budget change could not be completed."}</div>}
      <div className="metric-grid budget-metrics">
        <article className="metric-card featured"><span>Safe to spend</span><Amount value={budget.safe_to_spend} currency={budget.currency} /><small>Cash less budget/recurring obligations, linked goal reserves, and planning commitments</small></article>
        <article className="metric-card"><span>Planned income</span><Amount value={budget.planned_income} currency={budget.currency} /><small>Actual {formatMoney(budget.actual_income, budget.currency)}</small></article>
        <article className="metric-card"><span>Budgeted</span><Amount value={budget.available_with_rollover} currency={budget.currency} /><small>{formatMoney(budget.budgeted, budget.currency)} base plan</small></article>
        <article className="metric-card"><span>Spent</span><Amount value={budget.spent} currency={budget.currency} /><small>This month</small></article>
        <article className="metric-card"><span>Remaining</span><Amount value={budget.remaining} currency={budget.currency} /><small>Includes rollover</small></article>
        <article className="metric-card"><span>Unallocated income</span><Amount value={budget.unallocated} currency={budget.currency} /><small>Planned income less base budget</small></article>
      </div>
      {budget.source === "unplanned" && budget.categories.length === 0 ? <EmptyState title="No budget for this month" message="Create a monthly budget or switch to Year and set an annual plan once for the whole year." /> : (
        <section className="panel budget-category-panel">
          <div className="panel-heading"><div><span className="eyebrow">Planned vs actual</span><h2>Category budget</h2></div><span className="as-of">Recurring reserve {formatMoney(budget.upcoming_recurring, budget.currency)} · goal reserves {formatMoney(budget.goal_reserves, budget.currency)} · planning gap {formatMoney(budget.planning_commitments, budget.currency)}</span></div>
          <div className="budget-category-list">{budget.categories.map((row) => {
            const percent = Math.max(0, numberFromMoney(row.percent_used));
            return <article className={`budget-category-row status-${row.status}`} key={row.category.id}><div className="budget-category-heading"><div><strong>{row.category.name}</strong><span>{row.status === "over" ? "Over budget" : row.status === "close" ? "Getting close" : row.status === "no_budget" ? "No budget" : "On track"}</span></div><div><strong>{formatMoney(row.spent_amount, budget.currency)} / {formatMoney(row.available_amount, budget.currency)}</strong><span>{formatMoney(row.remaining_amount, budget.currency)} remaining</span></div></div><div className="budget-progress"><span style={{ width: `${Math.min(percent, 100)}%` }} /></div>{numberFromMoney(row.rollover_amount) !== 0 && <small className="budget-rollover-note">Base {formatMoney(row.base_amount, budget.currency)} · rollover {formatMoney(row.rollover_amount, budget.currency, { showSign: true })}</small>}</article>;
          })}</div>
        </section>
      )}
    </>
  );
}

function YearBudget({ year, data, plan, categories }: { year: number; data: YearBudgetView; plan: AnnualBudgetPlan; categories: CategorySelection }) {
  const [editing, setEditing] = useState(false);
  if (editing) return <AnnualPlanEditor year={year} plan={plan} categories={categories} onClose={() => setEditing(false)} />;
  return (
    <>
      <div className="budget-toolbar"><span className="budget-source-badge">{data.has_annual_plan ? "Annual plan active" : "No annual plan"}</span><button className="button primary" type="button" onClick={() => setEditing(true)}>{data.has_annual_plan ? "Edit annual plan" : "Create annual plan"}</button></div>
      <div className="summary-grid recurring-summary budget-year-summary">
        <article className="metric-card featured"><span>Annual planned income</span><Amount value={data.planned_income} currency={data.currency} /><small>YTD actual {formatMoney(data.actual_income, data.currency)}</small></article>
        <article className="metric-card"><span>Annual category goals</span><Amount value={data.budgeted} currency={data.currency} /><small>All 12 months</small></article>
        <article className="metric-card"><span>Spent YTD</span><Amount value={data.spent} currency={data.currency} /><small>Against interpreted transaction data</small></article>
        <article className="metric-card"><span>Annual unallocated</span><Amount value={data.unallocated} currency={data.currency} /><small>Income not assigned to categories</small></article>
      </div>
      {data.categories.length ? <section className="panel budget-category-panel"><div className="panel-heading"><div><span className="eyebrow">Year to date</span><h2>{year} progress</h2></div></div><div className="budget-year-list">{data.categories.map((row) => { const percent = Math.max(0, numberFromMoney(row.percent_used)); return <article className="budget-year-row" key={row.category.id}><div><strong>{row.category.name}</strong><span>YTD target {formatMoney(row.ytd_planned_amount, data.currency)}</span></div><div className="budget-progress"><span style={{ width: `${Math.min(percent, 100)}%` }} /></div><div><strong>{formatMoney(row.spent_amount, data.currency)} / {formatMoney(row.planned_amount, data.currency)}</strong><span>{percent.toFixed(0)}% of annual goal</span></div></article>; })}</div></section> : <EmptyState title="No annual goals yet" message="Create an annual plan to turn your usual monthly budget into a set-it-once baseline." />}
    </>
  );
}

export function BudgetPage({ embedded = false }: { embedded?: boolean } = {}) {
  const [view, setView] = useState<"month" | "year">("month");
  const [month, setMonth] = useState(currentMonth());
  const year = Number(month.slice(0, 4));
  const categories = useQuery({ queryKey: queryKeys.categories, queryFn: () => apiRequest<CategorySelection>("/categories/selection") });
  const monthBudget = useQuery({ queryKey: queryKeys.budgetMonth(month), queryFn: () => apiRequest<MonthlyBudgetView>(`/budget/months/${month}`) });
  const yearBudget = useQuery({ queryKey: queryKeys.budgetYear(year), queryFn: () => apiRequest<YearBudgetView>(`/budget/years/${year}`), enabled: view === "year" });
  const annualPlan = useQuery({ queryKey: queryKeys.annualBudgetPlan(year), queryFn: () => apiRequest<AnnualBudgetPlan>(`/budget/years/${year}/plan`), enabled: view === "year" });
  const busy = categories.isPending || (view === "month" ? monthBudget.isPending : yearBudget.isPending || annualPlan.isPending);
  const failed = categories.isError || (view === "month" ? monthBudget.isError : yearBudget.isError || annualPlan.isError);
  const description = view === "month" ? monthLabel(month) : `${year} annual plan and year-to-date progress`;
  const selector = useMemo(() => <div className="budget-view-controls"><div className="segmented-control"><button type="button" className={view === "month" ? "active" : ""} onClick={() => setView("month")}>Month</button><button type="button" className={view === "year" ? "active" : ""} onClick={() => setView("year")}>Year</button></div>{view === "month" ? <div className="month-control"><button type="button" aria-label="Previous month" onClick={() => setMonth((value) => shiftMonth(value, -1))}>‹</button><label><span className="sr-only">Budget month</span><input type="month" value={month} onChange={(event) => setMonth(event.target.value)} /></label><button type="button" aria-label="Next month" onClick={() => setMonth((value) => shiftMonth(value, 1))}>›</button></div> : <label className="year-control"><span className="sr-only">Budget year</span><input type="number" min="2000" max="2200" value={year} onChange={(event) => { const next = Math.min(2200, Math.max(2000, Number(event.target.value) || year)); setMonth(`${next}-${month.slice(5, 7)}`); }} /></label>}</div>, [view, month, year]);

  return (
    <div className={`page-container budget-page${embedded ? " embedded-page" : ""}`}>
      <PageHeader title="Budget" description={description} actions={selector} />
      {busy && <LoadingState label="Calculating your budget" />}
      {failed && <ErrorState message="Your budget could not be loaded." onRetry={() => { void categories.refetch(); void monthBudget.refetch(); void yearBudget.refetch(); void annualPlan.refetch(); }} />}
      {categories.data && view === "month" && monthBudget.data && <MonthBudget month={month} budget={monthBudget.data} categories={categories.data} />}
      {categories.data && view === "year" && yearBudget.data && annualPlan.data && <YearBudget year={year} data={yearBudget.data} plan={annualPlan.data} categories={categories.data} />}
      <p className="budget-footnote">Budget uses your transaction overrides, rules, transfers, and exclusions from <Link to="/transactions">Transactions</Link>. Annual targets remain unchanged by rollover; rollover only changes what is available in a month.</p>
    </div>
  );
}
