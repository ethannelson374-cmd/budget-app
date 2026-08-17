import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { FinancialCalendarEvent, FinancialCalendarView, RecurringStreamsResponse } from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { formatDate, formatMoney, formatPercent, numberFromMoney } from "../lib/format";

type CalendarMode = "timeline" | "month";

function currentMonth() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

function shiftMonth(value: string, delta: number) {
  const [year, month] = value.split("-").map(Number);
  const date = new Date(year, month - 1 + delta, 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`;
}

function eventSearch(event: FinancialCalendarEvent) {
  const search = new URLSearchParams({ sort: "date", direction: "desc" });
  const filters = event.filters;
  if (filters.start_date) search.set("start_date", filters.start_date);
  if (filters.end_date) search.set("end_date", filters.end_date);
  if (filters.account_id) search.set("account_id", String(filters.account_id));
  if (filters.category_id) search.set("category_id", String(filters.category_id));
  if (filters.kind) search.set("kind", filters.kind);
  if (filters.search) search.set("search", filters.search);
  return search.toString();
}

function eventLabel(event: FinancialCalendarEvent) {
  if (event.status === "observed") return "Posted";
  if (event.status === "pending") return "Pending";
  if (event.status === "planned") return "Planned";
  return "Expected";
}

function eventIcon(event: FinancialCalendarEvent) {
  if (event.kind === "income" || event.kind === "refund") return "+";
  if (event.kind === "debt") return "D";
  if (event.kind === "subscription") return "S";
  if (event.kind === "savings") return "↗";
  return "−";
}

function statusCopy(data: FinancialCalendarView) {
  if (data.summary.status === "historical") return "Projection is available for the current and future months.";
  if (data.summary.status === "low_cash") return "Projected cash falls below zero before the month ends.";
  if (data.summary.status === "attention") return "Projected cash falls below your configured reserve.";
  return "Projected cash stays above your configured reserve.";
}

function BalanceRibbon({ data }: { data: FinancialCalendarView }) {
  const points = data.projection;
  const geometry = useMemo(() => {
    if (!points.length) return null;
    const width = 920;
    const height = 160;
    const left = 24;
    const right = 24;
    const top = 28;
    const bottom = 30;
    const values = points.map((point) => numberFromMoney(point.balance));
    const reserve = numberFromMoney(data.summary.reserve_balance);
    const minimum = Math.min(...values, reserve);
    const maximum = Math.max(...values, reserve);
    const spread = Math.max(maximum - minimum, Math.max(Math.abs(maximum), 1) * 0.08, 1);
    const low = minimum - spread * 0.18;
    const high = maximum + spread * 0.18;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const coords = points.map((point, index) => ({
      point,
      x: left + (points.length <= 1 ? plotWidth / 2 : index / (points.length - 1) * plotWidth),
      y: top + (high - numberFromMoney(point.balance)) / (high - low) * plotHeight,
    }));
    const line = `M ${coords.map((item) => `${item.x.toFixed(1)} ${item.y.toFixed(1)}`).join(" L ")}`;
    const reserveY = top + (high - reserve) / (high - low) * plotHeight;
    return { width, height, left, right, coords, line, reserveY };
  }, [data.summary.reserve_balance, points]);

  if (!geometry) {
    return <div className="calendar-projection-empty">Historical month · no forward balance projection</div>;
  }
  return (
    <div className="calendar-balance-ribbon">
      <div className="calendar-ribbon-heading"><span>Projected cash path</span><small>Expected/planned activity · pending items are shown but not re-applied</small></div>
      <svg viewBox={`0 0 ${geometry.width} ${geometry.height}`} role="img" aria-label={`Projected cash balance for ${data.period.label}`}>
        <defs>
          <linearGradient id="calendar-balance-line" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#52f4dc"/><stop offset="54%" stopColor="#54a9ff"/><stop offset="100%" stopColor="#9d69ff"/>
          </linearGradient>
          <filter id="calendar-balance-glow" x="-30%" y="-80%" width="160%" height="260%"><feGaussianBlur stdDeviation="5" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
          <radialGradient id="calendar-event-orb" cx="30%" cy="22%" r="74%"><stop offset="0%" stopColor="#fff"/><stop offset="22%" stopColor="#9ffcf3"/><stop offset="62%" stopColor="#57a9ff"/><stop offset="100%" stopColor="#7759ff"/></radialGradient>
        </defs>
        <line className="calendar-reserve-line" x1={geometry.left} x2={geometry.width - geometry.right} y1={geometry.reserveY} y2={geometry.reserveY}/>
        <path className="calendar-balance-shadow" d={geometry.line} transform="translate(0 8)"/>
        <path className="calendar-balance-line" d={geometry.line} stroke="url(#calendar-balance-line)" filter="url(#calendar-balance-glow)"/>
        {geometry.coords.filter((item) => item.point.event_count > 0).map((item) => <g key={item.point.date}><circle className="calendar-ribbon-orb-shadow" cx={item.x + 2} cy={item.y + 6} r="6"/><circle className="calendar-ribbon-orb" cx={item.x} cy={item.y} r="5.5" fill="url(#calendar-event-orb)"><title>{`${formatDate(item.point.date, true)} · ${formatMoney(item.point.balance, data.currency)}`}</title></circle></g>)}
        <text className="calendar-ribbon-label" x={geometry.left} y={geometry.height - 8}>{formatDate(points[0].date, true)}</text>
        <text className="calendar-ribbon-label" x={geometry.width - geometry.right} y={geometry.height - 8} textAnchor="end">{formatDate(points.at(-1)!.date, true)}</text>
      </svg>
    </div>
  );
}

function EventInspector({ event, data }: { event: FinancialCalendarEvent; data: FinancialCalendarView }) {
  const impact = numberFromMoney(event.impact);
  return (
    <aside className={`calendar-event-inspector ${event.kind}`} aria-live="polite">
      <div className="calendar-event-orb" aria-hidden="true">{eventIcon(event)}</div>
      <div className="calendar-inspector-copy"><span>{eventLabel(event)} · {event.source_detail}</span><strong>{event.name}</strong><small>{formatDate(event.date, true)}{event.account ? ` · ${event.account.name}` : ""}{event.cadence ? ` · ${event.cadence}` : ""}</small></div>
      <div className="calendar-inspector-value"><strong className={impact >= 0 ? "positive" : "negative"}>{formatMoney(event.impact, data.currency, { showSign: true })}</strong>{event.price_change_pct && Math.abs(numberFromMoney(event.price_change_pct)) >= 5 ? <small className="warning">{formatPercent(event.price_change_pct)} vs prior average</small> : <small>{event.category?.name ?? event.kind}</small>}</div>
      <div className="calendar-inspector-actions"><Link className="button secondary" to={`/transactions?${eventSearch(event)}`}>View activity</Link><Link className="button secondary" to="/advisor" state={{ prompt: event.ask_prompt }}>Ask Budget</Link></div>
    </aside>
  );
}

function TimelineView({ data, selectedId, onSelect }: { data: FinancialCalendarView; selectedId: string | null; onSelect: (id: string) => void }) {
  if (!data.events.length) return <EmptyState title="No scheduled financial activity" message="Budget will add recurring income, bills, subscriptions, pending transactions, and dated debt payments as patterns become available." />;
  return (
    <div className="financial-timeline">
      {data.events.map((event) => {
        const impact = numberFromMoney(event.impact);
        const isToday = event.date === data.period.today;
        return (
          <button key={event.id} type="button" className={`timeline-event ${event.kind}${selectedId === event.id ? " selected" : ""}`} onClick={() => onSelect(event.id)}>
            <span className="timeline-date"><strong>{new Date(`${event.date}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</strong><small>{isToday ? "Today" : eventLabel(event)}</small></span>
            <span className="timeline-rail"><i /></span>
            <span className="timeline-event-orb" aria-hidden="true">{eventIcon(event)}</span>
            <span className="timeline-event-copy"><strong>{event.name}</strong><small>{event.source_detail}{event.account ? ` · ${event.account.name}` : ""}</small></span>
            <span className={`timeline-event-value ${impact >= 0 ? "positive" : "negative"}`}><strong>{formatMoney(event.impact, data.currency, { showSign: true })}</strong><small>{event.category?.name ?? event.kind}</small></span>
          </button>
        );
      })}
    </div>
  );
}

function MonthView({ data, selectedId, onSelect }: { data: FinancialCalendarView; selectedId: string | null; onSelect: (id: string) => void }) {
  const [year, month] = data.period.month.split("-").map(Number);
  const days = new Date(year, month, 0).getDate();
  const firstDay = new Date(year, month - 1, 1).getDay();
  const byDay = new Map<number, FinancialCalendarEvent[]>();
  for (const event of data.events) {
    const day = Number(event.date.slice(-2));
    byDay.set(day, [...(byDay.get(day) ?? []), event]);
  }
  return (
    <div className="financial-month-grid" role="grid" aria-label={`${data.period.label} financial calendar`}>
      {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map((day) => <div className="calendar-weekday" key={day} role="columnheader">{day}</div>)}
      {Array.from({ length: firstDay }, (_, index) => <div className="calendar-day empty" key={`empty-${index}`} aria-hidden="true" />)}
      {Array.from({ length: days }, (_, index) => {
        const day = index + 1;
        const date = `${data.period.month}-${String(day).padStart(2, "0")}`;
        const events = byDay.get(day) ?? [];
        return (
          <div className={`calendar-day${date === data.period.today ? " today" : ""}`} key={date} role="gridcell">
            <span className="calendar-day-number">{day}</span>
            <div className="calendar-day-events">
              {events.slice(0, 3).map((event) => <button key={event.id} className={`calendar-day-event ${event.kind}${selectedId === event.id ? " selected" : ""}`} type="button" onClick={() => onSelect(event.id)}><span>{event.name}</span><strong>{formatMoney(event.impact, data.currency, { showSign: true })}</strong></button>)}
              {events.length > 3 && <small>+{events.length - 3} more</small>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RecurringPatterns({ data }: { data: FinancialCalendarView }) {
  return (
    <section className="panel calendar-pattern-panel">
      <div className="panel-heading"><div><span className="eyebrow">Pattern engine</span><h2>Recurring baseline</h2><p>Detected patterns drive expected calendar events; posted activity remains visually distinct from forecasts.</p></div></div>
      <div className="calendar-pattern-metrics">
        <div><span>Detected streams</span><strong>{data.recurring.detected_streams}</strong></div>
        <div><span>Monthly inflow</span><strong>{formatMoney(data.recurring.monthly_inflow_estimate, data.currency)}</strong></div>
        <div><span>Monthly outflow</span><strong>{formatMoney(data.recurring.monthly_outflow_estimate, data.currency)}</strong></div>
        <div><span>Forecast basis</span><strong>Observed patterns</strong><small>No invented due dates</small></div>
      </div>
    </section>
  );
}

export function RecurringPage() {
  const queryClient = useQueryClient();
  const [month, setMonth] = useState(currentMonth);
  const [mode, setMode] = useState<CalendarMode>("timeline");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const calendarQuery = useQuery({ queryKey: queryKeys.financialCalendar(month), queryFn: () => apiRequest<FinancialCalendarView>(`/financial-calendar?month=${month}`) });
  const rebuild = useMutation({
    mutationFn: () => apiRequest<RecurringStreamsResponse>("/recurring/rebuild", { method: "POST" }),
    onSuccess: async (data) => {
      queryClient.setQueryData(queryKeys.recurring, data);
      await queryClient.invalidateQueries({ queryKey: ["financial-calendar"] });
    },
  });

  const data = calendarQuery.data;
  const selected = data?.events.find((event) => event.id === selectedId) ?? data?.events[0] ?? null;
  const summaryStatus = data?.summary.status ?? "historical";

  return (
    <div className="page-container financial-calendar-page">
      <PageHeader
        title="Financial calendar"
        description="See paydays, recurring bills, subscriptions, debt payments, and projected cash pressure before they happen."
        actions={<div className="calendar-header-actions"><button className="button secondary" type="button" disabled={rebuild.isPending} onClick={() => rebuild.mutate()}><Icon name="refresh" />{rebuild.isPending ? "Analyzing…" : "Reanalyze"}</button></div>}
      />

      {calendarQuery.isPending && <LoadingState label="Building your financial calendar" />}
      {calendarQuery.isError && <ErrorState message="Financial calendar could not be loaded." onRetry={() => void calendarQuery.refetch()} />}
      {data && (
        <>
          <div className="calendar-toolbar panel">
            <div className="calendar-month-control">
              <button className="icon-button" type="button" aria-label="Previous month" onClick={() => { setSelectedId(null); setMonth((value) => shiftMonth(value, -1)); }}>‹</button>
              <label><span className="sr-only">Calendar month</span><input type="month" value={month} onChange={(event) => { setSelectedId(null); setMonth(event.target.value || currentMonth()); }} /></label>
              <button className="icon-button" type="button" aria-label="Next month" onClick={() => { setSelectedId(null); setMonth((value) => shiftMonth(value, 1)); }}>›</button>
            </div>
            <div className="calendar-view-tabs" role="group" aria-label="Calendar view">
              <button type="button" className={mode === "timeline" ? "active" : ""} onClick={() => setMode("timeline")}>Timeline</button>
              <button type="button" className={mode === "month" ? "active" : ""} onClick={() => setMode("month")}>Calendar</button>
            </div>
          </div>

          <section className={`calendar-summary-grid ${summaryStatus}`} aria-label="Financial calendar summary">
            <article className="panel calendar-summary-card featured"><span>Projected month end</span><strong>{data.summary.projected_month_end ? formatMoney(data.summary.projected_month_end, data.currency) : "Historical"}</strong><small>{statusCopy(data)}</small></article>
            <article className="panel calendar-summary-card"><span>Expected in</span><strong className="positive">{formatMoney(data.summary.expected_inflow, data.currency)}</strong><small>{data.summary.expected_events} future/known events</small></article>
            <article className="panel calendar-summary-card"><span>Expected out</span><strong>{formatMoney(data.summary.expected_outflow, data.currency)}</strong><small>Recurring and dated commitments</small></article>
            <article className="panel calendar-summary-card"><span>Lowest projected cash</span><strong className={summaryStatus === "low_cash" || summaryStatus === "attention" ? "warning" : ""}>{data.summary.lowest_projected_balance ? formatMoney(data.summary.lowest_projected_balance, data.currency) : "—"}</strong><small>{data.summary.lowest_balance_date ? formatDate(data.summary.lowest_balance_date, true) : `${data.summary.observed_events} observed events`}</small></article>
          </section>

          <section className="panel financial-calendar-hero">
            <div className="panel-heading calendar-panel-heading"><div><span className="eyebrow">Cash timing</span><h2>{data.period.label}</h2><p>{data.summary.observed_events} posted · {data.summary.expected_events} future/known</p></div><div className={`calendar-health-chip ${summaryStatus}`}>{summaryStatus === "healthy" ? "Above reserve" : summaryStatus === "attention" ? "Reserve pressure" : summaryStatus === "low_cash" ? "Low cash risk" : "Historical"}</div></div>
            <BalanceRibbon data={data} />
            <div className="calendar-workspace">
              <div className="calendar-view-surface">{mode === "timeline" ? <TimelineView data={data} selectedId={selected?.id ?? null} onSelect={setSelectedId} /> : <MonthView data={data} selectedId={selected?.id ?? null} onSelect={setSelectedId} />}</div>
              {selected && <EventInspector event={selected} data={data} />}
            </div>
          </section>

          <RecurringPatterns data={data} />
        </>
      )}
    </div>
  );
}
