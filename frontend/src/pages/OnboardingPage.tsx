import { useEffect, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { ApiError, apiRequest } from "../api/client";
import { queryKeys, useSetupOptions } from "../api/queries";
import type {
  CategorySelection,
  FinancialGoalWrite,
  FinancialGoalsResponse,
  OnboardingStatus,
  PayFrequency,
  PlaidConnectionsResponse,
  PlaidLinkTokenResponse,
  UserSettings,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { Brand } from "../components/Brand";
import { ErrorState, LoadingState } from "../components/States";
import { clearPlaidLinkSession, createPlaidHandler, rememberPlaidLinkSession } from "../lib/plaid";

const STEPS = ["Welcome", "Your money", "Bank", "Budget", "Goal", "Privacy", "Ready"] as const;

type BudgetStart = "annual" | "monthly" | "later";

function currentMonth(): string {
  const date = new Date();
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : "That step could not be saved.";
}

export function OnboardingPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { user, refresh } = useAuth();
  const options = useSetupOptions();
  const settings = useQuery({ queryKey: queryKeys.settings, queryFn: () => apiRequest<UserSettings>("/settings") });
  const categories = useQuery({ queryKey: queryKeys.categories, queryFn: () => apiRequest<CategorySelection>("/categories/selection") });
  const connections = useQuery({ queryKey: queryKeys.plaidConnections, queryFn: () => apiRequest<PlaidConnectionsResponse>("/plaid/connections") });
  const goals = useQuery({ queryKey: queryKeys.goals, queryFn: () => apiRequest<FinancialGoalsResponse>("/planning/goals") });
  const onboarding = useQuery({ queryKey: ["first-run-onboarding"], queryFn: () => apiRequest<OnboardingStatus>("/onboarding") });
  const [step, setStep] = useState<number>(user?.settings.onboarding_step ?? 0);
  const [pageError, setPageError] = useState<string | null>(null);

  useEffect(() => {
    if (onboarding.data) setStep(onboarding.data.step);
  }, [onboarding.data]);

  const progress = Math.round((step / (STEPS.length - 1)) * 100);
  const loading = options.isPending || settings.isPending || categories.isPending || connections.isPending || goals.isPending || onboarding.isPending;
  const failed = options.isError || settings.isError || categories.isError || connections.isError || goals.isError || onboarding.isError;

  const saveProgress = useMutation({
    mutationFn: (next: number) => apiRequest<OnboardingStatus>("/onboarding", { method: "PATCH", body: JSON.stringify({ step: next }) }),
    onSuccess: (saved) => { setStep(saved.step); setPageError(null); },
    onError: (error) => setPageError(errorMessage(error)),
  });

  const go = (next: number) => saveProgress.mutate(Math.max(0, Math.min(6, next)));

  if (loading) return <main className="centered-page onboarding-shell"><Brand linked={false} /><LoadingState label="Preparing your Budget setup" /></main>;
  if (failed || !settings.data || !categories.data || !options.data || !connections.data || !goals.data) {
    return <main className="centered-page onboarding-shell"><Brand linked={false} /><ErrorState title="Setup could not load" message="Budget couldn't prepare your first-time setup. Try again." onRetry={() => { void settings.refetch(); void categories.refetch(); void connections.refetch(); void goals.refetch(); void onboarding.refetch(); }} /></main>;
  }

  return (
    <main className="onboarding-shell">
      <div className="onboarding-aurora" aria-hidden="true" />
      <header className="onboarding-topbar"><Brand linked={false} /><span>First-time setup</span></header>
      <section className="onboarding-stage" aria-labelledby="onboarding-title">
        <div className="onboarding-progress-head"><div><span className="eyebrow">STEP {step + 1} OF {STEPS.length}</span><strong>{STEPS[step]}</strong></div><span>{progress}%</span></div>
        <div className="onboarding-progress-track" aria-label={`${progress}% complete`}><span style={{ width: `${progress}%` }} /></div>
        <div className="onboarding-orbs" aria-hidden="true">{STEPS.map((label, index) => <span className={index <= step ? "active" : ""} key={label} />)}</div>
        {pageError && <div className="inline-alert" role="alert">{pageError}</div>}
        {step === 0 && <WelcomeStep name={user?.username ?? "there"} onNext={() => go(1)} busy={saveProgress.isPending} />}
        {step === 1 && <MoneyStep initial={settings.data} currencies={options.data.currencies} payFrequencies={options.data.pay_frequencies} onSaved={(saved) => { queryClient.setQueryData(queryKeys.settings, saved); go(2); }} onBack={() => setStep(0)} />}
        {step === 2 && <BankStep data={connections.data} onRefresh={async () => { await connections.refetch(); }} onNext={() => go(3)} onBack={() => setStep(1)} />}
        {step === 3 && <BudgetStep settings={settings.data} categories={categories.data} onCategories={(saved) => queryClient.setQueryData(queryKeys.categories, saved)} onNext={() => go(4)} onBack={() => setStep(2)} />}
        {step === 4 && <GoalStep goals={goals.data} onSaved={(saved) => { queryClient.setQueryData(queryKeys.goals, saved); go(5); }} onSkip={() => go(5)} onBack={() => setStep(3)} />}
        {step === 5 && <PrivacyStep initial={settings.data} onSaved={(saved) => { queryClient.setQueryData(queryKeys.settings, saved); go(6); }} onBack={() => setStep(4)} />}
        {step === 6 && <ReadyStep connections={connections.data.connections.length} goals={goals.data.goals.length} onBack={() => setStep(5)} onFinish={async () => {
          try {
            await apiRequest<OnboardingStatus>("/onboarding/complete", { method: "POST" });
            await refresh();
            navigate("/dashboard", { replace: true });
          } catch (error) { setPageError(errorMessage(error)); }
        }} />}
      </section>
    </main>
  );
}

function WelcomeStep({ name, onNext, busy }: { name: string; onNext: () => void; busy: boolean }) {
  return <div className="onboarding-copy"><span className="onboarding-hero-orb" aria-hidden="true">B</span><h1 id="onboarding-title">Welcome, {name}.</h1><p>Before we drop you into the dashboard, we'll set up the basics so Budget understands your money from day one.</p><div className="onboarding-feature-row"><span>Private by default</span><span>Bank connection optional</span><span>Change anything later</span></div><div className="onboarding-actions"><button className="button primary" type="button" disabled={busy} onClick={onNext}>Start setup</button></div></div>;
}

function MoneyStep({ initial, currencies, payFrequencies, onSaved, onBack }: { initial: UserSettings; currencies: Array<{ code: string; name: string }>; payFrequencies: Array<{ value: PayFrequency; label: string }>; onSaved: (saved: UserSettings) => void; onBack: () => void }) {
  const [currency, setCurrency] = useState(initial.currency);
  const [timezone, setTimezone] = useState(initial.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC");
  const [income, setIncome] = useState(initial.annual_gross_income ?? "");
  const [frequency, setFrequency] = useState<PayFrequency | "">(initial.pay_frequency ?? "");
  const save = useMutation({ mutationFn: () => apiRequest<UserSettings>("/settings", { method: "PATCH", body: JSON.stringify({ currency, timezone, annual_gross_income: income || null, pay_frequency: income ? frequency || null : null }) }), onSuccess: onSaved });
  const submit = (event: FormEvent) => { event.preventDefault(); if (income && !frequency) return; save.mutate(); };
  return <form className="onboarding-copy" onSubmit={submit}><span className="eyebrow">Your money</span><h1 id="onboarding-title">Give Budget a little context.</h1><p>This sets your reporting currency, local dates, and income context for forecasts and Ask Budget.</p>{save.isError && <div className="inline-alert">{errorMessage(save.error)}</div>}<div className="form-grid two-columns"><label>Currency<select value={currency} onChange={(e) => setCurrency(e.target.value)}>{currencies.map((item) => <option key={item.code} value={item.code}>{item.code} — {item.name}</option>)}</select></label><label>Timezone<input value={timezone} onChange={(e) => setTimezone(e.target.value)} /></label><label>Annual gross income <span className="optional">Optional</span><input inputMode="decimal" value={income} onChange={(e) => setIncome(e.target.value)} placeholder="78000" /></label><label>Pay frequency <span className="optional">Optional</span><select value={frequency} onChange={(e) => setFrequency(e.target.value as PayFrequency | "")}><option value="">Not set</option>{payFrequencies.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label></div>{income && !frequency && <small className="field-hint danger-text">Choose a pay frequency when income is set.</small>}<WizardActions back={onBack} nextLabel="Save and continue" busy={save.isPending} disabled={Boolean(income && !frequency)} /></form>;
}

function BankStep({ data, onRefresh, onNext, onBack }: { data: PlaidConnectionsResponse; onRefresh: () => Promise<void>; onNext: () => void; onBack: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const exchange = useMutation({ mutationFn: ({ publicToken, metadata }: { publicToken: string; metadata: PlaidLinkSuccessMetadata }) => apiRequest<PlaidConnectionsResponse>("/plaid/exchange", { method: "POST", body: JSON.stringify({ public_token: publicToken, institution_id: metadata.institution?.institution_id ?? null, accounts: metadata.accounts.map(({ name, mask }) => ({ name, mask })) }) }), onSuccess: async () => { clearPlaidLinkSession(); setNotice("Bank connected. Budget is importing your accounts."); await onRefresh(); }, onError: (e) => { clearPlaidLinkSession(); setError(errorMessage(e)); } });
  const connect = useMutation({ mutationFn: () => apiRequest<PlaidLinkTokenResponse>("/plaid/link-token", { method: "POST" }), onSuccess: (response) => {
    rememberPlaidLinkSession({ token: response.link_token, mode: response.mode, connectionId: response.connection_id, returnTo: "/onboarding" });
    let handler: PlaidHandler | undefined;
    try { handler = createPlaidHandler({ token: response.link_token, onSuccess: (publicToken, metadata) => { handler?.destroy(); if (!publicToken) { setError("Plaid did not return a connection token."); return; } exchange.mutate({ publicToken, metadata }); }, onExit: (plaidError) => { handler?.destroy(); clearPlaidLinkSession(); if (plaidError) setError("The bank connection was not completed. You can try again or skip for now."); }, onLoad: () => handler?.open() }); } catch (e) { clearPlaidLinkSession(); setError(errorMessage(e)); }
  }, onError: (e) => setError(errorMessage(e)) });
  return <div className="onboarding-copy"><span className="eyebrow">Connect your money</span><h1 id="onboarding-title">Bring your accounts in automatically.</h1><p>Plaid can securely connect your bank and import balances and transactions. You can skip this and use manual accounts instead.</p>{error && <div className="inline-alert">{error}</div>}{notice && <div className="inline-alert success">{notice}</div>}<div className="onboarding-choice-card"><span className="onboarding-bank-orb" aria-hidden="true">$</span><div><strong>{data.connections.length ? `${data.connections.length} institution${data.connections.length === 1 ? "" : "s"} connected` : "Connect a bank with Plaid"}</strong><small>{data.configured ? `${data.environment === "production" ? "Production" : "Sandbox"} connection` : "Plaid is not configured on this server"}</small></div><button className="button secondary" type="button" disabled={!data.configured || connect.isPending || exchange.isPending} onClick={() => connect.mutate()}>{data.connections.length ? "Connect another" : "Connect bank"}</button></div><WizardActions back={onBack} nextLabel={data.connections.length ? "Continue" : "Skip for now"} busy={false} onNext={onNext} /></div>;
}

function BudgetStep({ settings, categories, onCategories, onNext, onBack }: { settings: UserSettings; categories: CategorySelection; onCategories: (saved: CategorySelection) => void; onNext: () => void; onBack: () => void }) {
  const [kind, setKind] = useState<BudgetStart>("later");
  const [plannedIncome, setPlannedIncome] = useState("");
  const [enabled, setEnabled] = useState(() => categories.categories.filter((item) => item.enabled).map((item) => item.key));
  const save = useMutation({ mutationFn: async () => {
    const keys = Array.from(new Set([...enabled, "other"]));
    const saved = await apiRequest<CategorySelection>("/categories/selection", { method: "PUT", body: JSON.stringify({ category_keys: keys }) });
    if (kind === "annual" && plannedIncome) await apiRequest(`/budget/years/${new Date().getFullYear()}/plan`, { method: "PUT", body: JSON.stringify({ planned_income: plannedIncome, notes: "Created during first-time setup", categories: [] }) });
    if (kind === "monthly" && plannedIncome) await apiRequest(`/budget/months/${currentMonth()}`, { method: "PUT", body: JSON.stringify({ mode: "standalone", planned_income: plannedIncome, notes: "Created during first-time setup", categories: [] }) });
    return saved;
  }, onSuccess: (saved) => { onCategories(saved); onNext(); } });
  return <div className="onboarding-copy"><span className="eyebrow">Budget starting point</span><h1 id="onboarding-title">How do you want to begin?</h1><p>Pick the categories you care about. If you already know your planned income, Budget can create the shell of an annual or monthly plan now.</p>{save.isError && <div className="inline-alert">{errorMessage(save.error)}</div>}<div className="onboarding-option-grid">{([['annual','Annual plan'],['monthly','This month'],['later','Set it up later']] as const).map(([value,label]) => <button type="button" key={value} className={`onboarding-option${kind === value ? " selected" : ""}`} onClick={() => setKind(value)}><strong>{label}</strong><small>{value === "annual" ? "Plan the year once and refine later." : value === "monthly" ? "Start with the current month." : "Just choose categories for now."}</small></button>)}</div>{kind !== "later" && <label>Planned {kind === "annual" ? "annual" : "monthly"} income<input inputMode="decimal" value={plannedIncome} onChange={(e) => setPlannedIncome(e.target.value)} placeholder={settings.annual_gross_income && kind === "annual" ? settings.annual_gross_income : "0"} /></label>}<fieldset className="onboarding-category-grid"><legend>Spending categories</legend>{categories.categories.map((item) => <label key={item.id}><input type="checkbox" checked={enabled.includes(item.key)} disabled={item.key === "other"} onChange={() => setEnabled((current) => current.includes(item.key) ? current.filter((key) => key !== item.key) : [...current, item.key])} /><span>{item.name}</span></label>)}</fieldset><WizardActions back={onBack} nextLabel="Save and continue" busy={save.isPending} onNext={() => save.mutate()} /></div>;
}

function GoalStep({ goals, onSaved, onSkip, onBack }: { goals: FinancialGoalsResponse; onSaved: (saved: FinancialGoalsResponse) => void; onSkip: () => void; onBack: () => void }) {
  const [name, setName] = useState(""); const [target, setTarget] = useState(""); const [current, setCurrent] = useState(""); const [monthly, setMonthly] = useState("");
  const save = useMutation({ mutationFn: () => apiRequest<FinancialGoalsResponse>("/planning/goals", { method: "POST", body: JSON.stringify({ name, goal_type: "savings", target_amount: target, current_amount: current || "0", monthly_contribution: monthly || "0", target_date: null, linked_account_id: null, priority: 100, active: true, notes: "Created during first-time setup" } satisfies FinancialGoalWrite) }), onSuccess: onSaved });
  if (goals.goals.length) return <div className="onboarding-copy"><span className="eyebrow">Goals</span><h1 id="onboarding-title">You've already got something to work toward.</h1><p>{goals.goals[0].name} is already in your plan, so there's nothing else you need to enter here.</p><WizardActions back={onBack} nextLabel="Continue" busy={false} onNext={onSkip} /></div>;
  return <form className="onboarding-copy" onSubmit={(e) => { e.preventDefault(); if (name && target) save.mutate(); else onSkip(); }}><span className="eyebrow">Goals</span><h1 id="onboarding-title">Anything you're working toward?</h1><p>Add one savings goal now, or skip it. You can build a full debt and goal strategy later in Plan.</p>{save.isError && <div className="inline-alert">{errorMessage(save.error)}</div>}<div className="form-grid two-columns"><label>Goal name <span className="optional">Optional</span><input value={name} onChange={(e) => setName(e.target.value)} placeholder="Emergency fund" /></label><label>Target amount<input inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} disabled={!name} placeholder="10000" /></label><label>Already saved<input inputMode="decimal" value={current} onChange={(e) => setCurrent(e.target.value)} disabled={!name} placeholder="0" /></label><label>Monthly contribution<input inputMode="decimal" value={monthly} onChange={(e) => setMonthly(e.target.value)} disabled={!name} placeholder="0" /></label></div><WizardActions back={onBack} nextLabel={name ? "Create goal" : "Skip for now"} busy={save.isPending} disabled={Boolean(name && !target)} /></form>;
}

function PrivacyStep({ initial, onSaved, onBack }: { initial: UserSettings; onSaved: (saved: UserSettings) => void; onBack: () => void }) {
  const [enabled, setEnabled] = useState(initial.advisor_enabled); const [merchants, setMerchants] = useState(initial.advisor_share_merchants); const [descriptions, setDescriptions] = useState(initial.advisor_include_descriptions); const [history, setHistory] = useState(initial.advisor_store_history);
  const save = useMutation({ mutationFn: () => apiRequest<UserSettings>("/settings", { method: "PATCH", body: JSON.stringify({ advisor_enabled: enabled, advisor_share_merchants: merchants, advisor_include_descriptions: descriptions, advisor_store_history: history }) }), onSuccess: onSaved });
  return <form className="onboarding-copy" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}><span className="eyebrow">Ask Budget privacy</span><h1 id="onboarding-title">You decide what AI can see.</h1><p>Budget's calculations stay deterministic. These controls decide what context may be sent to the configured AI provider when you ask a question.</p>{save.isError && <div className="inline-alert">{errorMessage(save.error)}</div>}<div className="onboarding-toggle-list"><label><span><strong>Enable Ask Budget</strong><small>Allow the read-only financial copilot.</small></span><input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} /></label><label><span><strong>Share merchant names</strong><small>Off by default; merchant-specific context is otherwise redacted.</small></span><input type="checkbox" checked={merchants} disabled={!enabled} onChange={(e) => setMerchants(e.target.checked)} /></label><label><span><strong>Include transaction descriptions</strong><small>Available only when merchant sharing is enabled.</small></span><input type="checkbox" checked={descriptions} disabled={!enabled || !merchants} onChange={(e) => setDescriptions(e.target.checked)} /></label><label><span><strong>Store Advisor conversations</strong><small>Turn off for private sessions that disappear after you leave.</small></span><input type="checkbox" checked={history} disabled={!enabled} onChange={(e) => setHistory(e.target.checked)} /></label></div><WizardActions back={onBack} nextLabel="Save privacy choices" busy={save.isPending} /></form>;
}

function ReadyStep({ connections, goals, onBack, onFinish }: { connections: number; goals: number; onBack: () => void; onFinish: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  return <div className="onboarding-copy ready-copy"><span className="onboarding-hero-orb ready" aria-hidden="true">✓</span><span className="eyebrow">You're ready</span><h1 id="onboarding-title">Budget is set up for you.</h1><p>Your account is ready. From here, the dashboard will start turning your balances, transactions, plans, and goals into one financial picture.</p><div className="onboarding-summary-grid"><div><span>Bank</span><strong>{connections ? `${connections} connected` : "Skipped"}</strong></div><div><span>Goals</span><strong>{goals ? `${goals} active` : "None yet"}</strong></div><div><span>Privacy</span><strong>Configured</strong></div></div><div className="onboarding-actions"><button className="button ghost" type="button" onClick={onBack}>Back</button><button className="button primary" type="button" disabled={busy} onClick={() => { setBusy(true); void onFinish().finally(() => setBusy(false)); }}>{busy ? "Finishing…" : "Go to my Dashboard"}</button></div></div>;
}

function WizardActions({ back, nextLabel, busy, disabled = false, onNext }: { back: () => void; nextLabel: string; busy: boolean; disabled?: boolean; onNext?: () => void }) {
  return <div className="onboarding-actions"><button className="button ghost" type="button" onClick={back}>Back</button><button className="button primary" type={onNext ? "button" : "submit"} onClick={onNext} disabled={busy || disabled}>{busy ? "Saving…" : nextLabel}</button></div>;
}
