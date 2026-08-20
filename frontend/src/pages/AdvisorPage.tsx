import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiEventStream, apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type {
  AdvisorConversation,
  AdvisorConversationDetail,
  AdvisorConversationList,
  AdvisorFact,
  AdvisorProposal,
  AdvisorProposalAction,
  AdvisorReply,
  AdvisorReportContext,
  AdvisorStatus,
  InsightItem,
} from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { ErrorState, LoadingState } from "../components/States";

interface ChatRow {
  key: string;
  role: "user" | "assistant";
  content: string;
  reply?: AdvisorReply | null;
  facts?: AdvisorFact[];
}

const starters = [
  "What should I focus on financially this month?",
  "Can I afford a $500 purchase right now?",
  "Where has my spending increased the most?",
  "Build me a plan to free up $300 per month.",
  "How can I pay my debt off faster?",
  "What happens if I save another $200 per month?",
];

function normalizeAdvisorText(text: string) {
  return text.replace(/\\n/g, "\n").replace(/\\t/g, "\t");
}

function renderInlineEmphasis(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, index) =>
    part.startsWith("**") && part.endsWith("**")
      ? <strong key={`${index}-${part}`}>{part.slice(2, -2)}</strong>
      : <span key={`${index}-${part}`}>{part}</span>
  );
}

function AdvisorText({ text }: { text: string }) {
  const paragraphs = normalizeAdvisorText(text).split(/\n+/).map((line) => line.trim()).filter(Boolean);
  return <div className="advisor-answer-text">{paragraphs.map((line, index) => <p key={`${index}-${line}`}>{renderInlineEmphasis(line)}</p>)}</div>;
}

function toRows(detail: AdvisorConversationDetail): ChatRow[] {
  return detail.messages.map((message) => ({ key: `saved-${message.id}`, role: message.role, content: message.content, reply: message.response, facts: message.response?.facts }));
}

function actionState(action: AdvisorProposalAction, state: Record<string, unknown>, currency: string): string {
  if ("amount" in state) return `${currency} ${String(state.amount)}`;
  if ("reserve_balance" in state) {
    const reserveMode = state.include_budget_reserve === false ? "cash reserve only" : "plus budget reserve";
    return `${currency} ${String(state.reserve_balance)} · ${reserveMode}`;
  }
  if ("strategy" in state) return `${String(state.strategy)} · ${currency} ${String(state.monthly_extra_budget ?? "0")}/mo extra`;
  return action.action_type.replaceAll("_", " ");
}

function AdvisorProposalCard({ proposalId }: { proposalId: number }) {
  const queryClient = useQueryClient();
  const proposal = useQuery({
    queryKey: queryKeys.advisorProposal(proposalId),
    queryFn: () => apiRequest<AdvisorProposal>(`/advisor/proposals/${proposalId}`),
  });
  const update = useMutation({
    mutationFn: (operation: "apply" | "reject" | "undo") => apiRequest<AdvisorProposal>(`/advisor/proposals/${proposalId}/${operation}`, { method: "POST" }),
    onSuccess: async (data) => {
      queryClient.setQueryData(queryKeys.advisorProposal(proposalId), data);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["budget-month"] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.goals }),
        queryClient.invalidateQueries({ queryKey: queryKeys.debts }),
        queryClient.invalidateQueries({ queryKey: queryKeys.forecast }),
        queryClient.invalidateQueries({ queryKey: ["insights"] }),
      ]);
    },
  });

  if (proposal.isPending) return <div className="advisor-proposal compact"><span>Preparing deterministic change preview…</span></div>;
  if (proposal.isError || !proposal.data) return <div className="advisor-proposal compact"><span>Action plan preview could not be loaded.</span></div>;
  const plan = proposal.data;
  const mutateError = update.error instanceof Error ? update.error.message : null;

  const apply = () => {
    if (window.confirm(`Apply “${plan.title}”? Budget will update only the financial settings shown in this preview.`)) update.mutate("apply");
  };
  const undo = () => {
    if (window.confirm(`Undo “${plan.title}”? Budget will restore the values that existed before this plan was applied.`)) update.mutate("undo");
  };

  return (
    <section className={`advisor-proposal status-${plan.status}`} aria-label="Advisor action plan">
      <div className="advisor-proposal-heading">
        <div><span className="eyebrow">Recommended plan</span><h4>{plan.title}</h4></div>
        <span className={`advisor-proposal-status ${plan.status}`}>{plan.status}</span>
      </div>
      <p>{plan.summary}</p>
      <div className="advisor-proposal-actions">
        {plan.actions.map((action, index) => (
          <div className="advisor-proposal-action" key={action.id}>
            <span className="advisor-proposal-number">{index + 1}</span>
            <div><strong>{action.label}</strong><p>{action.rationale}</p><small>{actionState(action, action.before, plan.currency)} <span aria-hidden="true">→</span> {actionState(action, action.after, plan.currency)}</small></div>
          </div>
        ))}
      </div>
      {plan.preview.impacts.length > 0 && (
        <div className="advisor-proposal-preview">
          <strong>Deterministic preview</strong>
          <dl>{plan.preview.impacts.map((impact) => <div key={impact.label}><dt>{impact.label}</dt><dd><span>{impact.before}</span><span aria-hidden="true">→</span><strong>{impact.after}</strong></dd></div>)}</dl>
        </div>
      )}
      {mutateError && <div className="inline-alert" role="alert">{mutateError}</div>}
      <div className="advisor-proposal-footer">
        <small>{plan.status === "draft" ? "Nothing changes until you approve this plan." : plan.status === "applied" ? "Applied by Budget after your approval." : plan.status === "undone" ? "The applied changes were restored." : plan.status === "rejected" ? "This plan was dismissed without changes." : "This plan expired without changes."}</small>
        <div>
          {plan.status === "draft" && <><button className="button secondary" type="button" disabled={update.isPending} onClick={() => update.mutate("reject")}>Dismiss</button><button className="button primary" type="button" disabled={update.isPending} onClick={apply}>{update.isPending ? "Applying…" : "Apply changes"}</button></>}
          {plan.status === "applied" && <button className="button secondary" type="button" disabled={update.isPending} onClick={undo}>{update.isPending ? "Restoring…" : "Undo plan"}</button>}
        </div>
      </div>
    </section>
  );
}

function ReplyCard({ row }: { row: ChatRow }) {
  const reply = row.reply;
  if (!reply) return <AdvisorText text={row.content || "Thinking…"} />;
  return (
    <div className="advisor-reply-card">
      <div className="advisor-reply-heading"><span className={`advisor-mode ${reply.mode}`}>{reply.mode}</span><span>{reply.confidence} confidence</span></div>
      <h3>{reply.headline}</h3>
      <AdvisorText text={reply.answer} />
      {reply.facts?.length > 0 && <dl className="advisor-facts">{reply.facts.map((fact) => <div key={`${fact.label}-${fact.value}`}><dt>{fact.label}</dt><dd>{fact.value}<small>{fact.detail}</small></dd></div>)}</dl>}
      {reply.warnings.length > 0 && <div className="advisor-warnings"><strong>Keep in mind</strong>{reply.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
      {reply.proposal_id ? <AdvisorProposalCard proposalId={reply.proposal_id} /> : null}
    </div>
  );
}

export function AdvisorPage({ embedded = false }: { embedded?: boolean } = {}) {
  const location = useLocation();
  const queryClient = useQueryClient();
  const routeState = (location.state as { insight?: InsightItem; intent?: "explain" | "plan"; report?: AdvisorReportContext; conversationId?: number; prompt?: string } | null);
  const routedInsight = routeState?.insight ?? null;
  const routedReport = routeState?.report ?? null;
  const initialPrompt = routeState?.prompt
    ? routeState.prompt
    : routedInsight
    ? routeState?.intent === "plan"
      ? `Build a practical action plan to address this insight: ${routedInsight.title}`
      : `Explain this insight and what I should do next: ${routedInsight.title}`
    : routedReport
      ? `Analyze this ${routedReport.label} report. What stands out, what improved or worsened, and what should I focus on next?`
      : "";
  const [attachedInsight, setAttachedInsight] = useState<InsightItem | null>(routedInsight);
  const [attachedReport, setAttachedReport] = useState<AdvisorReportContext | null>(routedReport);
  const [selectedId, setSelectedId] = useState<number | null>(routeState?.conversationId ?? null);
  const [messages, setMessages] = useState<ChatRow[]>([]);
  const [input, setInput] = useState(initialPrompt);
  const [busy, setBusy] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);

  const status = useQuery({ queryKey: queryKeys.advisorStatus, queryFn: () => apiRequest<AdvisorStatus>("/advisor/status") });
  const storeHistory = status.data?.store_history ?? true;
  const conversations = useQuery({
    queryKey: queryKeys.advisorConversations,
    queryFn: () => apiRequest<AdvisorConversationList>("/advisor/conversations"),
    enabled: status.data?.enabled === true && storeHistory,
  });
  const detail = useQuery({
    queryKey: queryKeys.advisorConversation(selectedId ?? 0),
    queryFn: () => apiRequest<AdvisorConversationDetail>(`/advisor/conversations/${selectedId}`),
    enabled: Boolean(selectedId && storeHistory && !busy && messages.length === 0),
  });

  useEffect(() => {
    if (detail.data && !busy) setMessages(toRows(detail.data));
  }, [detail.data, busy]);

  const createConversation = useMutation({
    mutationFn: () => apiRequest<AdvisorConversation>("/advisor/conversations", { method: "POST", body: JSON.stringify({}) }),
  });

  const deleteConversation = useMutation({
    mutationFn: (id: number) => apiRequest<{ ok: boolean }>(`/advisor/conversations/${id}`, { method: "DELETE" }),
    onSuccess: (_data, id) => {
      if (selectedId === id) newConversation();
      void queryClient.invalidateQueries({ queryKey: queryKeys.advisorConversations });
    },
  });

  const currentTitle = useMemo(() => {
    if (!storeHistory) return "Private session";
    return conversations.data?.conversations.find((item) => item.id === selectedId)?.title ?? "New conversation";
  }, [conversations.data, selectedId, storeHistory]);

  const newConversation = () => {
    setSelectedId(null);
    setMessages([]);
    setInput("");
    setAttachedInsight(null);
    setAttachedReport(null);
    setStreamError(null);
  };

  const openConversation = (id: number) => {
    if (busy) return;
    setMessages([]);
    setSelectedId(id);
    setAttachedInsight(null);
    setAttachedReport(null);
    setStreamError(null);
  };

  const send = async (prompt: string) => {
    const message = prompt.trim();
    if (!message || busy) return;
    setBusy(true);
    setStreamError(null);
    const insightForRequest = attachedInsight;
    const reportForRequest = attachedReport;
    setAttachedInsight(null);
    setAttachedReport(null);
    const userRow: ChatRow = { key: `user-${Date.now()}`, role: "user", content: message };
    const assistantKey = `assistant-${Date.now()}`;
    setMessages((current) => [...current, userRow, { key: assistantKey, role: "assistant", content: "", reply: null }]);
    setInput("");

    try {
      let conversationId = selectedId;
      if (!conversationId) {
        const created = await createConversation.mutateAsync();
        conversationId = created.id;
        setSelectedId(created.id);
      }
      let streamedText = "";
      let metaFacts: AdvisorFact[] = [];
      await apiEventStream(`/advisor/conversations/${conversationId}/messages/stream`, {
        method: "POST",
        body: JSON.stringify({
          message,
          insight_id: insightForRequest?.id ?? null,
          report_section: reportForRequest?.section ?? null,
          report_range: reportForRequest?.range ?? null,
        }),
      }, ({ event, data }) => {
        const payload = (data ?? {}) as Record<string, unknown>;
        if (event === "meta") {
          metaFacts = Array.isArray(payload.facts) ? payload.facts as AdvisorFact[] : [];
        } else if (event === "delta") {
          streamedText += String(payload.text ?? "");
          setMessages((current) => current.map((row) => row.key === assistantKey ? { ...row, content: streamedText, facts: metaFacts } : row));
        } else if (event === "done") {
          const reply = payload as unknown as AdvisorReply;
          setMessages((current) => current.map((row) => row.key === assistantKey ? { ...row, content: reply.answer, reply, facts: reply.facts } : row));
        } else if (event === "error") {
          throw new ApiError(String(payload.message ?? "Ask Budget could not complete the response."), { status: 503, code: String(payload.code ?? "advisor_stream_failed") });
        }
      });
      if (storeHistory) {
        await queryClient.invalidateQueries({ queryKey: queryKeys.advisorConversations });
        await queryClient.invalidateQueries({ queryKey: queryKeys.advisorConversation(conversationId) });
      } else {
        setSelectedId(null);
      }
    } catch (error) {
      const apiError = error instanceof ApiError ? error : null;
      setStreamError(apiError?.retryAfter ? `${apiError.message} Try again in about ${apiError.retryAfter} seconds.` : error instanceof Error ? error.message : "Ask Budget could not complete the response.");
      setMessages((current) => current.filter((row) => row.key !== assistantKey || row.content));
    } finally {
      setBusy(false);
    }
  };

  const submit = (event: FormEvent) => { event.preventDefault(); void send(input); };

  if (status.isPending) return <div className={`page-container advisor-page${embedded ? " embedded-page" : ""}`}><PageHeader title="Ask Budget" description="Financial answers grounded in Budget's own calculations." /><LoadingState label="Opening Advisor" /></div>;
  if (status.isError) return <div className={`page-container advisor-page${embedded ? " embedded-page" : ""}`}><PageHeader title="Ask Budget" /><ErrorState message="Advisor status could not be loaded." onRetry={() => void status.refetch()} /></div>;
  if (!status.data.available) return <div className={`page-container advisor-page${embedded ? " embedded-page" : ""}`}><PageHeader title="Ask Budget" description="Financial answers grounded in Budget's own calculations." /><section className="panel advisor-unavailable"><h2>AI Advisor is not configured yet</h2><p>The server needs an enabled AI provider before Ask Budget can answer questions.</p><Link className="button secondary" to="/settings">Open Settings</Link></section></div>;
  if (!status.data.enabled) return <div className={`page-container advisor-page${embedded ? " embedded-page" : ""}`}><PageHeader title="Ask Budget" /><section className="panel advisor-unavailable"><h2>Ask Budget is turned off</h2><p>You can enable the Advisor and choose its privacy options in Settings.</p><Link className="button primary" to="/settings">Enable in Settings</Link></section></div>;

  const detailLoading = Boolean(selectedId && storeHistory && !busy && messages.length === 0 && detail.isPending);
  return (
    <div className={`page-container advisor-page${embedded ? " embedded-page" : ""}`}>
      <PageHeader title="Ask Budget" description="Ask questions, model options, or review a plan before Budget changes anything." actions={<button className="button secondary" type="button" onClick={newConversation}>New conversation</button>} />
      {!storeHistory && <div className="notice-banner"><strong>Private session.</strong> Budget will not keep Advisor messages, and action plans are not created in private sessions.</div>}
      {attachedInsight && <div className="advisor-insight-context"><div><span className="eyebrow">Attached insight</span><strong>{attachedInsight.title}</strong><p>{attachedInsight.summary}</p></div><button type="button" className="button ghost" onClick={() => setAttachedInsight(null)}>Remove</button></div>}
      {attachedReport && <div className="advisor-insight-context"><div><span className="eyebrow">Attached report</span><strong>{attachedReport.label}</strong><p>Ask Budget will receive this report directly from Budget's deterministic reporting engine.</p></div><button type="button" className="button ghost" onClick={() => setAttachedReport(null)}>Remove</button></div>}
      <div className={`advisor-layout${storeHistory ? "" : " private"}`}>
        {storeHistory && <aside className="panel advisor-history"><div className="advisor-history-heading"><strong>Conversations</strong><button type="button" className="text-button" onClick={newConversation}>New</button></div>{conversations.isPending && <p className="muted-copy">Loading history…</p>}{conversations.data?.conversations.length ? <div className="advisor-history-list">{conversations.data.conversations.map((item) => <div className={`advisor-history-row${selectedId === item.id ? " active" : ""}`} key={item.id}><button type="button" className="advisor-history-open" onClick={() => openConversation(item.id)}><strong>{item.title}</strong><small>{new Date(item.updated_at).toLocaleDateString()}</small></button><button type="button" className="advisor-history-delete" aria-label={`Delete ${item.title}`} disabled={deleteConversation.isPending || busy} onClick={() => { if (window.confirm(`Delete ${item.title}?`)) deleteConversation.mutate(item.id); }}>×</button></div>)}</div> : <p className="muted-copy">No saved conversations yet.</p>}</aside>}
        <section className="panel advisor-chat">
          <div className="advisor-chat-heading"><div><span className="eyebrow">{storeHistory ? "Conversation" : "Not saved"}</span><h2>{currentTitle}</h2></div><span className="advisor-provider">{status.data.provider} · {status.data.model}</span></div>
          <div className="advisor-thread" aria-live="polite">
            {detailLoading ? <LoadingState label="Opening conversation" /> : messages.length === 0 ? <div className="advisor-empty"><h3>What do you want to know?</h3><p>Budget owns the math. Ask Budget can explain it or propose changes for you to review and approve.</p><div className="advisor-starters">{starters.map((starter) => <button type="button" key={starter} onClick={() => void send(starter)} disabled={busy}>{starter}</button>)}</div></div> : messages.map((row) => <article key={row.key} className={`advisor-message ${row.role}`}><div className="advisor-message-label">{row.role === "user" ? "You" : "Ask Budget"}</div>{row.role === "assistant" ? <ReplyCard row={row} /> : <p>{row.content}</p>}{row.reply?.suggested_questions?.length ? <div className="advisor-followups">{row.reply.suggested_questions.map((question) => <button type="button" key={question} disabled={busy} onClick={() => void send(question)}>{question}</button>)}</div> : null}</article>)}
          </div>
          {streamError && <div className="inline-alert" role="alert">{streamError}</div>}
          <form className="advisor-composer" onSubmit={submit}><label className="sr-only" htmlFor="advisor-message">Ask Budget</label><textarea id="advisor-message" rows={3} maxLength={4000} value={input} onChange={(event) => setInput(event.target.value)} placeholder="Ask Budget anything about your financial plan…" disabled={busy} /><div><span>Phase 3C-3 · AI may propose changes; Budget applies nothing without your approval.</span><button className="button primary" type="submit" disabled={busy || !input.trim()}>{busy ? "Thinking…" : "Ask Budget"}</button></div></form>
        </section>
      </div>
    </div>
  );
}
