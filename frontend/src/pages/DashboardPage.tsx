import { useEffect, useRef, useState, type DragEvent, type FormEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { ApiError, apiEventStream, apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type {
  AdvisorConversation,
  AdvisorReply,
  AdvisorStatus,
  DashboardCardId,
  DashboardCardPreference,
  DashboardCardSize,
  DashboardData,
  DashboardOnboarding,
  DashboardPreferences,
  DashboardPreset,
  InsightsResponse,
  MonthlyBudgetView,
} from "../api/types";
import { CashFlowSankeyWidget } from "../components/CashFlowSankey";
import { CategoryBars } from "../components/CategoryBars";
import { InsightCard } from "../components/InsightCard";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { TransactionList } from "../components/TransactionList";
import { currentMonth, formatDateTime, formatMoney, formatPercent, maskAccount, monthLabel, numberFromMoney } from "../lib/format";
import { useToast } from "../toast/ToastContext";

function shiftMonth(month: string, delta: number): string {
  const [year, monthNumber] = month.split("-").map(Number);
  const result = new Date(year, monthNumber - 1 + delta, 1);
  return `${result.getFullYear()}-${String(result.getMonth() + 1).padStart(2, "0")}`;
}

const DEFAULT_CARDS: DashboardCardPreference[] = [
  { id: "net_worth", size: "compact", visible: true },
  { id: "cash_available", size: "compact", visible: true },
  { id: "income", size: "compact", visible: true },
  { id: "spending", size: "compact", visible: true },
  { id: "net_cash_flow", size: "compact", visible: true },
  { id: "savings_rate", size: "compact", visible: true },
  { id: "cash_flow", size: "hero", visible: true },
  { id: "top_spending", size: "standard", visible: true },
  { id: "ask_budget", size: "hero", visible: true },
  { id: "budget", size: "standard", visible: true },
  { id: "insights", size: "hero", visible: true },
  { id: "recent_transactions", size: "hero", visible: true },
  { id: "accounts", size: "standard", visible: true },
  { id: "data_freshness", size: "compact", visible: true },
];

const CARD_SIZES: DashboardCardSize[] = ["compact", "standard", "hero"];

const CARD_LABELS: Record<DashboardCardId, string> = {
  net_worth: "Net worth",
  cash_available: "Cash available",
  income: "Income",
  spending: "Spending",
  net_cash_flow: "Net cash flow",
  savings_rate: "Savings rate",
  cash_flow: "Cash flow",
  top_spending: "Top spending",
  ask_budget: "Ask Budget",
  budget: "Budget progress",
  insights: "Financial intelligence",
  recent_transactions: "Recent transactions",
  accounts: "Accounts",
  data_freshness: "Data freshness",
};

const PRESETS: Record<Exclude<DashboardPreset, "custom">, Partial<Record<DashboardCardId, DashboardCardSize>>> = {
  everyday: Object.fromEntries(DEFAULT_CARDS.map((card) => [card.id, card.size])) as Record<DashboardCardId, DashboardCardSize>,
  minimal: {
    net_worth: "compact",
    cash_available: "compact",
    net_cash_flow: "compact",
    ask_budget: "standard",
    recent_transactions: "hero",
    data_freshness: "compact",
  },
  planning: {
    cash_available: "compact",
    net_cash_flow: "compact",
    budget: "hero",
    insights: "standard",
    ask_budget: "standard",
    accounts: "standard",
    data_freshness: "compact",
  },
  analytics: {
    net_worth: "compact",
    income: "compact",
    spending: "compact",
    savings_rate: "compact",
    cash_flow: "hero",
    top_spending: "standard",
    budget: "standard",
    insights: "hero",
    ask_budget: "standard",
  },
};

function applyPreset(name: Exclude<DashboardPreset, "custom">): DashboardCardPreference[] {
  const selected = PRESETS[name];
  const ordered = Object.keys(selected) as DashboardCardId[];
  const rest = DEFAULT_CARDS.map((card) => card.id).filter((id) => !ordered.includes(id));
  return [...ordered, ...rest].map((id) => ({
    id,
    size: selected[id] ?? DEFAULT_CARDS.find((card) => card.id === id)!.size,
    visible: id in selected,
  }));
}

function normalizeAdvisorText(text: string): string {
  return text.replace(/\\n/g, "\n").replace(/\\t/g, "\t");
}

function AdvisorMiniText({ text }: { text: string }) {
  const lines = normalizeAdvisorText(text).split(/\n+/).map((line) => line.trim()).filter(Boolean);
  return <div className="dashboard-advisor-answer">{lines.map((line, index) => <p key={`${index}-${line}`}>{line.replaceAll("**", "")}</p>)}</div>;
}

function AskBudgetCard({ prefill, onPrefillConsumed }: { prefill: string; onPrefillConsumed: () => void }) {
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [input, setInput] = useState("");
  const [answer, setAnswer] = useState("");
  const [reply, setReply] = useState<AdvisorReply | null>(null);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const status = useQuery({
    queryKey: queryKeys.advisorStatus,
    queryFn: () => apiRequest<AdvisorStatus>("/advisor/status"),
  });

  useEffect(() => {
    if (!prefill) return;
    setInput(prefill);
    inputRef.current?.focus();
    onPrefillConsumed();
  }, [prefill, onPrefillConsumed]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const message = input.trim();
    if (!message || busy || !status.data?.available || !status.data.enabled) return;
    setBusy(true);
    setError(null);
    setAnswer("");
    setReply(null);
    try {
      let id = conversationId;
      if (!id || !status.data.store_history) {
        const conversation = await apiRequest<AdvisorConversation>("/advisor/conversations", {
          method: "POST",
          body: JSON.stringify({ title: "Dashboard question" }),
        });
        id = conversation.id;
        if (status.data.store_history) setConversationId(id);
      }
      let streamed = "";
      await apiEventStream(
        `/advisor/conversations/${id}/messages/stream`,
        { method: "POST", body: JSON.stringify({ message }) },
        ({ event: eventName, data }) => {
          if (eventName === "delta" && data && typeof data === "object" && "text" in data) {
            streamed += String((data as { text: unknown }).text ?? "");
            setAnswer(streamed);
          }
          if (eventName === "done" && data && typeof data === "object") {
            const completed = data as AdvisorReply;
            setReply(completed);
            setAnswer(completed.answer);
          }
          if (eventName === "error" && data && typeof data === "object") {
            setError(String((data as { message?: unknown }).message ?? "Ask Budget could not complete the response."));
          }
        },
      );
      setInput("");
      if (!status.data.store_history) setConversationId(null);
      await queryClient.invalidateQueries({ queryKey: queryKeys.advisorConversations });
    } catch (requestError) {
      setError(requestError instanceof ApiError ? requestError.message : "Ask Budget could not complete the response.");
    } finally {
      setBusy(false);
    }
  };

  if (status.isPending) return <LoadingState label="Preparing Ask Budget" />;
  if (status.isError || !status.data?.available || !status.data.enabled) {
    return <EmptyState title="Ask Budget is unavailable" message={status.data?.enabled === false ? "Ask Budget is turned off in Settings." : "The AI advisor is not configured on this server."} action={<Link className="button secondary" to="/settings">Open settings</Link>} />;
  }

  return (
    <div className="dashboard-advisor-card-content">
      <div className="panel-heading dashboard-advisor-heading">
        <div><span className="eyebrow">Financial copilot</span><h2>Ask Budget</h2></div>
        <Link className="text-link" to="/advisor" state={conversationId ? { conversationId } : undefined}>Open full Advisor <span aria-hidden="true">↗</span></Link>
      </div>
      {answer ? (
        <div className="dashboard-advisor-response">
          <span className="advisor-mode">{reply?.mode ?? "answer"}</span>
          <AdvisorMiniText text={answer} />
          {reply?.facts?.length ? <div className="dashboard-advisor-facts">{reply.facts.slice(0, 3).map((fact) => <span key={`${fact.label}-${fact.value}`}><small>{fact.label}</small><strong>{fact.value}</strong></span>)}</div> : null}
        </div>
      ) : <p className="dashboard-advisor-prompt">Ask about spending, cash flow, goals, debt, or what deserves your attention next.</p>}
      {error && <div className="inline-alert" role="alert">{error}</div>}
      <form className="dashboard-advisor-form" onSubmit={submit}>
        <textarea ref={inputRef} rows={2} value={input} maxLength={4000} placeholder="Ask about your finances…" onChange={(event) => setInput(event.target.value)} />
        <div>
          <div className="dashboard-advisor-starters">
            <button type="button" onClick={() => setInput("What should I focus on financially this month?")}>Priorities</button>
            <button type="button" onClick={() => setInput("Where has my spending increased the most?")}>Spending</button>
            <button type="button" onClick={() => setInput("Can I afford a $500 purchase right now?")}>Affordability</button>
          </div>
          <button className="button primary" type="submit" disabled={busy || !input.trim()}>{busy ? "Thinking…" : "Ask"}</button>
        </div>
      </form>
    </div>
  );
}

function OnboardingCard({ onboarding }: { onboarding: DashboardOnboarding }) {
  const queryClient = useQueryClient();
  const { pushToast } = useToast();
  const dismiss = useMutation({
    mutationFn: () => apiRequest<DashboardOnboarding>("/dashboard/onboarding/dismiss", { method: "POST" }),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.dashboardOnboarding, data);
      pushToast("Getting-started checklist hidden.", "success");
    },
  });
  const progress = onboarding.total ? Math.round((onboarding.completed / onboarding.total) * 100) : 0;
  return (
    <section className="panel onboarding-card">
      <div className="panel-heading">
        <div><span className="eyebrow">Getting started</span><h2>Build your financial picture</h2><p>{onboarding.completed} of {onboarding.total} steps complete</p></div>
        <button className="text-button" type="button" disabled={dismiss.isPending} onClick={() => dismiss.mutate()}>Hide for now</button>
      </div>
      <div className="onboarding-progress" aria-label={`${progress}% complete`}><span style={{ width: `${progress}%` }} /></div>
      <div className="onboarding-task-grid">
        {onboarding.tasks.map((task) => <Link key={task.key} to={task.route} className={`onboarding-task${task.complete ? " complete" : ""}`}><span className="onboarding-check" aria-hidden="true">{task.complete ? "✓" : "○"}</span><span><strong>{task.label}</strong><small>{task.description}</small></span><span aria-hidden="true">→</span></Link>)}
      </div>
    </section>
  );
}

function FreshnessCard({ data }: { data: DashboardData }) {
  const plaidAccounts = data.accounts.filter((account) => account.source_type === "plaid");
  const lastSync = plaidAccounts.map((account) => account.last_synced_at).filter((value): value is string => Boolean(value)).sort().at(-1) ?? null;
  const ageHours = lastSync ? (Date.now() - new Date(lastSync).getTime()) / 3_600_000 : null;
  const status = plaidAccounts.length === 0 ? "manual" : lastSync === null ? "never" : ageHours !== null && ageHours > 12 ? "stale" : "fresh";
  return (
    <div className="data-freshness-card">
      <div className="panel-heading"><div><span className="eyebrow">Connections</span><h2>Data freshness</h2></div><span className={`freshness-badge ${status}`}>{status === "manual" ? "Manual only" : status === "never" ? "Not synced" : status === "stale" ? "May be stale" : "Fresh"}</span></div>
      <p>{status === "manual" ? "No linked bank accounts are contributing automated data yet." : lastSync ? `Latest linked-account update ${formatDateTime(lastSync)}.` : "Linked accounts have not completed a balance sync yet."}</p>
      <Link className="text-link" to="/accounts">Manage connections <span aria-hidden="true">→</span></Link>
    </div>
  );
}

function WidgetShell({ card, customizing, onDragStart, onDrop, onMove, onResize, onHide, children }: {
  card: DashboardCardPreference;
  customizing: boolean;
  onDragStart: (id: DashboardCardId) => void;
  onDrop: (id: DashboardCardId) => void;
  onMove: (id: DashboardCardId, delta: number) => void;
  onResize: (id: DashboardCardId, size: DashboardCardSize) => void;
  onHide: (id: DashboardCardId) => void;
  children: ReactNode;
}) {
  const [resizing, setResizing] = useState(false);
  const resizeStart = useRef<{ x: number; index: number } | null>(null);
  const currentIndex = CARD_SIZES.indexOf(card.size);

  const resizeTo = (index: number) => {
    const next = CARD_SIZES[Math.max(0, Math.min(CARD_SIZES.length - 1, index))];
    if (next !== card.size) onResize(card.id, next);
  };

  const startResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!customizing) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeStart.current = { x: event.clientX, index: currentIndex };
    setResizing(true);
  };

  const moveResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!customizing || !resizeStart.current) return;
    const delta = event.clientX - resizeStart.current.x;
    const steps = delta >= 150 ? 2 : delta >= 58 ? 1 : delta <= -150 ? -2 : delta <= -58 ? -1 : 0;
    resizeTo(resizeStart.current.index + steps);
  };

  const finishResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!resizeStart.current) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
    resizeStart.current = null;
    setResizing(false);
  };

  return (
    <div
      className={`dashboard-widget size-${card.size}${customizing ? " customizing" : ""}${resizing ? " resizing" : ""}`}
      data-card-id={card.id}
      data-card-size={card.size}
      draggable={customizing && !resizing}
      onDragStart={(event: DragEvent<HTMLDivElement>) => {
        if (resizing) {
          event.preventDefault();
          return;
        }
        event.dataTransfer.effectAllowed = "move";
        onDragStart(card.id);
      }}
      onDragOver={(event) => { if (customizing) event.preventDefault(); }}
      onDrop={(event) => { event.preventDefault(); onDrop(card.id); }}
    >
      {customizing && (
        <div className="dashboard-widget-tools">
          <span className="drag-handle" title="Drag card to reorder" aria-hidden="true">⠿</span>
          <strong>{CARD_LABELS[card.id]}</strong>
          <span className="dashboard-size-readout">{card.size}</span>
          <div>
            <button type="button" title="Move earlier" aria-label={`Move ${CARD_LABELS[card.id]} earlier`} onClick={() => onMove(card.id, -1)}>↑</button>
            <button type="button" title="Move later" aria-label={`Move ${CARD_LABELS[card.id]} later`} onClick={() => onMove(card.id, 1)}>↓</button>
            <button type="button" title="Hide card" aria-label={`Hide ${CARD_LABELS[card.id]}`} onClick={() => onHide(card.id)}>×</button>
          </div>
        </div>
      )}
      <div className="dashboard-widget-body">{children}</div>
      {customizing && (
        <div
          className="dashboard-resize-handle"
          role="slider"
          tabIndex={0}
          aria-label={`Resize ${CARD_LABELS[card.id]}`}
          aria-valuemin={0}
          aria-valuemax={2}
          aria-valuenow={currentIndex}
          aria-valuetext={card.size}
          title="Drag horizontally to resize"
          onPointerDown={startResize}
          onPointerMove={moveResize}
          onPointerUp={finishResize}
          onPointerCancel={finishResize}
          onKeyDown={(event) => {
            if (event.key === "ArrowRight" || event.key === "ArrowUp") {
              event.preventDefault();
              resizeTo(currentIndex + 1);
            }
            if (event.key === "ArrowLeft" || event.key === "ArrowDown") {
              event.preventDefault();
              resizeTo(currentIndex - 1);
            }
            if (event.key === "Home") {
              event.preventDefault();
              resizeTo(0);
            }
            if (event.key === "End") {
              event.preventDefault();
              resizeTo(CARD_SIZES.length - 1);
            }
          }}
        >
          <span aria-hidden="true" />
        </div>
      )}
    </div>
  );
}

export function DashboardPage() {
  const [month, setMonth] = useState(currentMonth);
  const dashboard = useQuery({ queryKey: queryKeys.dashboard(month), queryFn: () => apiRequest<DashboardData>(`/dashboard?month=${encodeURIComponent(month)}`) });
  const budget = useQuery({ queryKey: queryKeys.budgetMonth(month), queryFn: () => apiRequest<MonthlyBudgetView>(`/budget/months/${month}`) });
  const insights = useQuery({ queryKey: queryKeys.insights("active"), queryFn: () => apiRequest<InsightsResponse>("/insights/refresh", { method: "POST" }), staleTime: 60_000 });
  const preferences = useQuery({ queryKey: queryKeys.dashboardPreferences, queryFn: () => apiRequest<DashboardPreferences>("/dashboard/preferences") });
  const onboarding = useQuery({ queryKey: queryKeys.dashboardOnboarding, queryFn: () => apiRequest<DashboardOnboarding>("/dashboard/onboarding") });

  return (
    <div className="page-container dashboard-page">
      <PageHeader title="Dashboard" description={monthLabel(month)} actions={<div className="dashboard-header-actions"><div className="month-control"><button type="button" aria-label="Previous month" onClick={() => setMonth((value) => shiftMonth(value, -1))}>‹</button><label><span className="sr-only">Dashboard month</span><input type="month" value={month} max={currentMonth()} onChange={(event) => setMonth(event.target.value)} /></label><button type="button" aria-label="Next month" disabled={month >= currentMonth()} onClick={() => setMonth((value) => shiftMonth(value, 1))}>›</button></div></div>} />
      {dashboard.isPending && <LoadingState label="Calculating this month" />}
      {dashboard.isError && <ErrorState message="Your dashboard could not be loaded." onRetry={() => void dashboard.refetch()} />}
      {dashboard.data && <DashboardContent data={dashboard.data} budget={budget.data} insights={insights.data} preferences={preferences.data} onboarding={onboarding.data} />}
    </div>
  );
}

function DashboardContent({ data, budget, insights, preferences, onboarding }: {
  data: DashboardData;
  budget?: MonthlyBudgetView;
  insights?: InsightsResponse;
  preferences?: DashboardPreferences;
  onboarding?: DashboardOnboarding;
}) {
  const queryClient = useQueryClient();
  const { pushToast } = useToast();
  const { summary } = data;
  const [customizing, setCustomizing] = useState(false);
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [draftCards, setDraftCards] = useState<DashboardCardPreference[]>(preferences?.cards ?? DEFAULT_CARDS);
  const [draftPreset, setDraftPreset] = useState<DashboardPreset>(preferences?.preset ?? "everyday");
  const [draggedId, setDraggedId] = useState<DashboardCardId | null>(null);
  const [askPrompt, setAskPrompt] = useState("");

  useEffect(() => {
    if (!customizing && preferences?.cards) {
      setDraftCards(preferences.cards);
      setDraftPreset(preferences.preset);
    }
  }, [preferences, customizing]);

  const savePreferences = useMutation({
    mutationFn: (payload: { cards: DashboardCardPreference[]; preset: DashboardPreset }) => apiRequest<DashboardPreferences>("/dashboard/preferences", { method: "PUT", body: JSON.stringify(payload) }),
    onSuccess: (saved) => {
      queryClient.setQueryData(queryKeys.dashboardPreferences, saved);
      setCustomizing(false);
      setLibraryOpen(false);
      pushToast("Dashboard layout saved.", "success");
    },
    onError: (error) => pushToast(error instanceof Error ? error.message : "Dashboard layout could not be saved.", "error"),
  });

  const startCustomize = () => {
    setDraftCards(preferences?.cards ?? DEFAULT_CARDS);
    setDraftPreset(preferences?.preset ?? "everyday");
    setCustomizing(true);
  };
  const cancelCustomize = () => {
    setDraftCards(preferences?.cards ?? DEFAULT_CARDS);
    setDraftPreset(preferences?.preset ?? "everyday");
    setCustomizing(false);
    setLibraryOpen(false);
  };
  const preset = (name: Exclude<DashboardPreset, "custom">) => {
    setDraftCards(applyPreset(name));
    setDraftPreset(name);
  };
  const moveCard = (id: DashboardCardId, delta: number) => setDraftCards((cards) => {
    const index = cards.findIndex((card) => card.id === id);
    const target = Math.max(0, Math.min(cards.length - 1, index + delta));
    if (index < 0 || target === index) return cards;
    const next = [...cards];
    const [card] = next.splice(index, 1);
    next.splice(target, 0, card);
    return next;
  });
  const dropCard = (targetId: DashboardCardId) => {
    if (!draggedId || draggedId === targetId) return;
    setDraftCards((cards) => {
      const source = cards.findIndex((card) => card.id === draggedId);
      const target = cards.findIndex((card) => card.id === targetId);
      if (source < 0 || target < 0) return cards;
      const next = [...cards];
      const [card] = next.splice(source, 1);
      next.splice(target, 0, card);
      return next;
    });
    setDraggedId(null);
    setDraftPreset("custom");
  };
  const resizeCard = (id: DashboardCardId, size: DashboardCardSize) => setDraftCards((cards) =>
    cards.map((card) => card.id === id ? { ...card, size } : card),
  );
  const setVisibility = (id: DashboardCardId, visible: boolean) => {
    setDraftCards((cards) => cards.map((card) => card.id === id ? { ...card, visible } : card));
    setDraftPreset("custom");
  };

  const activeCards = (customizing ? draftCards : preferences?.cards ?? DEFAULT_CARDS).filter((card) => card.visible);
  const hiddenCards = draftCards.filter((card) => !card.visible);
  const savingsTone = summary.savings_rate === null ? "neutral" : numberFromMoney(summary.savings_rate) >= 0 ? "positive" : "negative";

  const askAbout = (prompt: string) => {
    setAskPrompt(prompt);
    requestAnimationFrame(() => document.querySelector('[data-card-id="ask_budget"]')?.scrollIntoView({ behavior: "smooth", block: "center" }));
  };

  const renderCard = (card: DashboardCardPreference): ReactNode => {
    const id = card.id;
    if (id === "net_worth") return <article className="metric-card dashboard-metric-card featured"><span>Net worth</span><strong>{formatMoney(summary.net_worth, data.currency)}</strong><small>Across included accounts</small></article>;
    if (id === "cash_available") return <article className="metric-card dashboard-metric-card"><span>Cash available</span><strong>{formatMoney(summary.cash_available, data.currency)}</strong><small>Available in cash accounts</small></article>;
    if (id === "income") return <article className="metric-card dashboard-metric-card"><span>Income</span><strong className="positive">{formatMoney(summary.income, data.currency)}</strong><small>This month</small></article>;
    if (id === "spending") return <article className="metric-card dashboard-metric-card"><span>Spending</span><strong>{formatMoney(summary.spending, data.currency)}</strong><small>Transfers excluded</small><button className="metric-ask" type="button" onClick={() => askAbout("Where has my spending increased the most this month?")}>Ask Budget</button></article>;
    if (id === "net_cash_flow") return <article className="metric-card dashboard-metric-card"><span>Net cash flow</span><strong className={numberFromMoney(summary.net_cash_flow) >= 0 ? "positive" : "negative"}>{formatMoney(summary.net_cash_flow, data.currency, { showSign: true })}</strong><small>Income less spending</small><button className="metric-ask" type="button" onClick={() => askAbout("Explain my current monthly cash flow and what I should focus on next.")}>Ask why</button></article>;
    if (id === "savings_rate") return <article className="metric-card dashboard-metric-card"><span>Savings rate</span><strong className={savingsTone}>{formatPercent(summary.savings_rate)}</strong><small>{summary.savings_rate === null ? "No income this month" : "Of monthly income"}</small></article>;
    if (id === "cash_flow") return <CashFlowSankeyWidget dashboard={data} size={card.size} onAsk={askAbout} />;
    if (id === "top_spending") return <section className="panel dashboard-fill-card"><div className="panel-heading"><div><span className="eyebrow">This month</span><h2>Top spending</h2></div>{data.spending_by_category.length > 0 && <button className="text-button" type="button" onClick={() => askAbout("What stands out about my top spending categories this month?")}>Ask Budget</button>}</div><CategoryBars categories={data.spending_by_category} currency={data.currency} /></section>;
    if (id === "ask_budget") return <section className="panel dashboard-fill-card dashboard-advisor-widget"><AskBudgetCard prefill={askPrompt} onPrefillConsumed={() => setAskPrompt("")} /></section>;
    if (id === "budget") return <section className="panel dashboard-fill-card dashboard-budget-panel"><div className="panel-heading"><div><span className="eyebrow">Monthly budget</span><h2>{budget && budget.source !== "unplanned" ? `${formatMoney(budget.spent, budget.currency)} spent of ${formatMoney(budget.available_with_rollover, budget.currency)}` : "No budget plan yet"}</h2></div><Link className="text-link" to="/budget">{budget && budget.source !== "unplanned" ? "Open budget" : "Create budget"} <span aria-hidden="true">→</span></Link></div>{budget && budget.source !== "unplanned" ? <div className="dashboard-budget-summary"><div><strong>{formatMoney(budget.remaining, budget.currency)}</strong><span>Remaining</span></div><div><strong>{formatMoney(budget.safe_to_spend, budget.currency)}</strong><span>Safe to spend</span></div><div><strong>{budget.categories.filter((row) => row.status === "close").length}</strong><span>Getting close</span></div><div><strong>{budget.categories.filter((row) => row.status === "over").length}</strong><span>Over budget</span></div></div> : <p className="muted-copy">Set a yearly budget or customize a month to unlock safe-to-spend guidance.</p>}</section>;
    if (id === "insights") return <section className="panel dashboard-fill-card dashboard-insights"><div className="panel-heading"><div><span className="eyebrow">Financial intelligence</span><h2>What needs your attention</h2></div><Link className="text-link" to="/insights">View all {insights?.active_count ?? 0} <span aria-hidden="true">→</span></Link></div>{insights?.insights.length ? <div className="dashboard-insight-list">{insights.insights.slice(0, 3).map((insight) => <InsightCard key={insight.id} insight={insight} compact />)}</div> : <EmptyState title="Nothing urgent right now" message="As your financial history grows, Budget will surface deterministic insights here." action={<Link className="button secondary" to="/insights">Review insights</Link>} />}</section>;
    if (id === "recent_transactions") return <section className="panel dashboard-fill-card recent-panel"><div className="panel-heading"><div><span className="eyebrow">Latest activity</span><h2>Recent transactions</h2></div><Link className="text-link" to="/transactions">View all <span aria-hidden="true">→</span></Link></div>{data.recent_transactions.length ? <TransactionList transactions={data.recent_transactions} compact /> : <EmptyState title="No transactions yet" message="Connect a bank or add a manual transaction to start building history." action={<Link className="button secondary" to="/accounts">Add financial data</Link>} />}</section>;
    if (id === "accounts") return <section className="panel dashboard-fill-card dashboard-accounts"><div className="panel-heading"><div><span className="eyebrow">Balance snapshot</span><h2>Accounts</h2></div><Link className="text-link" to="/accounts">View all <span aria-hidden="true">→</span></Link></div>{data.accounts.length ? <div className="dashboard-account-list">{data.accounts.slice(0, 4).map((account) => <article key={account.id}><div><strong>{account.name}</strong><span>{account.institution ?? account.account_type} · {maskAccount(account.mask)}</span></div><strong>{formatMoney(account.current_balance, account.currency)}</strong></article>)}</div> : <EmptyState title="No accounts yet" message="Add a manual account or connect a bank to populate your dashboard." action={<Link className="button secondary" to="/accounts">Add an account</Link>} />}</section>;
    return <section className="panel dashboard-fill-card"><FreshnessCard data={data} /></section>;
  };

  return (
    <>
      {data.excluded_currencies.length > 0 && <div className="notice-banner" role="status"><strong>Some balances are shown separately.</strong> Totals include {data.currency} only. Excluded: {data.excluded_currencies.join(", ")}.</div>}
      {onboarding && !onboarding.complete && !onboarding.dismissed && <OnboardingCard onboarding={onboarding} />}
      <div className="dashboard-customize-bar">
        <div><strong>Your dashboard</strong><span>{customizing ? "Drag cards to reorder. Grab the lower-right glass edge to snap between Compact, Standard, and Hero." : "Your layout follows you wherever you sign in."}</span></div>
        {customizing ? <div className="dashboard-customize-actions"><button className="button secondary" type="button" onClick={() => setLibraryOpen((value) => !value)}>+ Add card</button><button className="button secondary" type="button" onClick={() => preset("everyday")}>Reset layout</button><button className="button secondary" type="button" onClick={cancelCustomize}>Cancel</button><button className="button primary" type="button" disabled={savePreferences.isPending} onClick={() => savePreferences.mutate({ cards: draftCards, preset: draftPreset })}>{savePreferences.isPending ? "Saving…" : "Done"}</button></div> : <button className="button secondary" type="button" onClick={startCustomize}>Customize</button>}
      </div>
      {customizing && <div className="dashboard-preset-bar"><span>Presets</span>{(["everyday", "minimal", "planning", "analytics"] as const).map((name) => <button key={name} type="button" className={draftPreset === name ? "active" : ""} onClick={() => preset(name)}>{name}</button>)}</div>}
      {customizing && libraryOpen && <section className="panel dashboard-card-library"><div className="panel-heading"><div><span className="eyebrow">Card library</span><h2>Add to Dashboard</h2></div></div>{hiddenCards.length ? <div className="dashboard-library-grid">{hiddenCards.map((card) => <button type="button" key={card.id} onClick={() => setVisibility(card.id, true)}><strong>{CARD_LABELS[card.id]}</strong><span>Add card +</span></button>)}</div> : <p className="muted-copy">Every available card is already on your dashboard.</p>}</section>}
      <div className="dashboard-custom-grid">{activeCards.map((card) => <WidgetShell key={card.id} card={card} customizing={customizing} onDragStart={setDraggedId} onDrop={dropCard} onMove={(id, delta) => { moveCard(id, delta); setDraftPreset("custom"); }} onResize={(id, size) => { resizeCard(id, size); setDraftPreset("custom"); }} onHide={(id) => setVisibility(id, false)}>{renderCard(card)}</WidgetShell>)}</div>
    </>
  );
}
