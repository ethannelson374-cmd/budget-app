import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type {
  CashFlowLink,
  CashFlowNode,
  CashFlowRange,
  CashFlowSankeyData,
  DashboardCardSize,
  DashboardData,
} from "../api/types";
import { formatMoney, formatPercent, numberFromMoney } from "../lib/format";
import { EmptyState, ErrorState, LoadingState } from "./States";

const SVG_WIDTH = 1100;
const NODE_WIDTH = 198;
const NODE_HEIGHT = 48;
const LEFT_X = 20;
const HUB_X = 514;
const HUB_WIDTH = 72;
const RIGHT_X = SVG_WIDTH - NODE_WIDTH - 20;
const FLOW_BAND = 154;

const FLOW_TONES: Record<CashFlowLink["kind"], [string, string]> = {
  income: ["var(--aurora-cyan)", "var(--aurora-blue)"],
  refund: ["#78f3d0", "var(--aurora-cyan)"],
  shortfall: ["var(--negative)", "#ff9d77"],
  expense: ["var(--aurora-blue)", "var(--aurora-violet)"],
  debt: ["#ffbe65", "#ff7a7a"],
  savings: ["#55efc4", "var(--aurora-cyan)"],
};

function evenlySpaced(count: number, height: number): number[] {
  if (count <= 0) return [];
  const top = 58;
  const bottom = height - 58;
  if (count === 1) return [(top + bottom) / 2];
  return Array.from({ length: count }, (_, index) => top + ((bottom - top) * index) / (count - 1));
}

function moneyNumber(value: string): number {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function buildTransactionUrl(link: CashFlowLink, data: CashFlowSankeyData): string | null {
  if (!link.filters) return null;
  const params = new URLSearchParams({
    start_date: data.period.start,
    end_date: data.period.end,
  });
  if (link.filters.kind) params.set("kind", link.filters.kind);
  if (link.filters.category_id) params.set("category_id", String(link.filters.category_id));
  if (link.filters.search) params.set("search", link.filters.search);
  return `/transactions?${params.toString()}`;
}

function comparisonText(node: CashFlowNode | undefined): string | null {
  if (!node || node.change_percent === null) return null;
  const change = numberFromMoney(node.change_percent);
  if (Math.abs(change) < 0.05) return "About even with the previous period";
  return `${change > 0 ? "+" : ""}${change.toFixed(1)}% vs. the previous period`;
}

function SankeyGraphic({
  data,
  condensed = false,
  onAsk,
}: {
  data: CashFlowSankeyData;
  condensed?: boolean;
  onAsk: (prompt: string) => void;
}) {
  const leftNodes = data.nodes.filter((node) => ["income_source", "refund", "shortfall"].includes(node.kind));
  const rightNodes = data.nodes.filter((node) => ["expense", "debt", "savings"].includes(node.kind));
  const hub = data.nodes.find((node) => node.kind === "hub");
  const incoming = data.links.filter((link) => link.target === "cash-in");
  const outgoing = data.links.filter((link) => link.source === "cash-in");
  const flowTotal = Math.max(
    incoming.reduce((sum, link) => sum + moneyNumber(link.amount), 0),
    outgoing.reduce((sum, link) => sum + moneyNumber(link.amount), 0),
    1,
  );
  const height = Math.max(condensed ? 330 : 430, Math.max(leftNodes.length, rightNodes.length) * (condensed ? 48 : 58) + 90);
  const leftY = evenlySpaced(leftNodes.length, height);
  const rightY = evenlySpaced(rightNodes.length, height);
  const leftPositions = new Map(leftNodes.map((node, index) => [node.id, leftY[index]]));
  const rightPositions = new Map(rightNodes.map((node, index) => [node.id, rightY[index]]));
  const hubCenter = height / 2;
  const bandWidth = (amount: string) => (moneyNumber(amount) / flowTotal) * FLOW_BAND;

  let incomingCursor = hubCenter - FLOW_BAND / 2;
  const incomingTargets = new Map<string, number>();
  incoming.forEach((link) => {
    const width = bandWidth(link.amount);
    incomingTargets.set(link.id, incomingCursor + width / 2);
    incomingCursor += width;
  });
  let outgoingCursor = hubCenter - FLOW_BAND / 2;
  const outgoingSources = new Map<string, number>();
  outgoing.forEach((link) => {
    const width = bandWidth(link.amount);
    outgoingSources.set(link.id, outgoingCursor + width / 2);
    outgoingCursor += width;
  });

  const defaultLink = outgoing[0] ?? incoming[0] ?? null;
  const [selectedId, setSelectedId] = useState<string | null>(defaultLink?.id ?? null);
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const activeLink = data.links.find((link) => link.id === (hoveredId ?? selectedId)) ?? defaultLink;
  const activeNode = activeLink
    ? data.nodes.find((node) => node.id === (activeLink.source === "cash-in" ? activeLink.target : activeLink.source))
    : undefined;
  const transactionUrl = activeLink ? buildTransactionUrl(activeLink, data) : null;
  const share = activeLink?.share_percent ?? (activeLink ? String((moneyNumber(activeLink.amount) / flowTotal) * 100) : null);

  const paths = data.links.map((link) => {
    const width = bandWidth(link.amount);
    if (link.target === "cash-in") {
      const sourceY = leftPositions.get(link.source) ?? hubCenter;
      const targetY = incomingTargets.get(link.id) ?? hubCenter;
      return {
        link,
        width,
        d: `M ${LEFT_X + NODE_WIDTH} ${sourceY} C 330 ${sourceY}, 420 ${targetY}, ${HUB_X} ${targetY}`,
      };
    }
    const sourceY = outgoingSources.get(link.id) ?? hubCenter;
    const targetY = rightPositions.get(link.target) ?? hubCenter;
    return {
      link,
      width,
      d: `M ${HUB_X + HUB_WIDTH} ${sourceY} C 685 ${sourceY}, 770 ${targetY}, ${RIGHT_X} ${targetY}`,
    };
  });

  if (!hub || data.links.length === 0) {
    return <EmptyState title="No cash flow to map" message="Income and spending in this period will appear here as they are categorized." />;
  }

  return (
    <div className={`cash-flow-sankey${condensed ? " condensed" : ""}`}>
      <div className="sankey-stage">
        <svg viewBox={`0 0 ${SVG_WIDTH} ${height}`} role="img" aria-label={`Cash flow map for ${data.period.label}`}>
          <defs>
            <linearGradient id="sankey-hub" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0" stopColor="rgba(255,255,255,.7)" />
              <stop offset=".16" stopColor="var(--aurora-cyan)" stopOpacity=".92" />
              <stop offset=".58" stopColor="var(--aurora-blue)" stopOpacity=".82" />
              <stop offset="1" stopColor="var(--aurora-violet)" stopOpacity=".74" />
            </linearGradient>
            <filter id="sankey-glow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="5" result="blur" />
              <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
            </filter>
            <filter id="sankey-soft-shadow" x="-50%" y="-50%" width="200%" height="220%">
              <feGaussianBlur stdDeviation="7" />
            </filter>
            {paths.map(({ link }) => {
              const [start, end] = FLOW_TONES[link.kind];
              return (
                <linearGradient key={link.id} id={`flow-${link.id.replace(/[^a-z0-9]/gi, "-")}`} x1="0" y1="0" x2="1" y2="0">
                  <stop offset="0" stopColor={start} stopOpacity=".88" />
                  <stop offset=".48" stopColor={end} stopOpacity=".74" />
                  <stop offset="1" stopColor={end} stopOpacity=".9" />
                </linearGradient>
              );
            })}
          </defs>

          <ellipse className="sankey-floor-glow" cx={SVG_WIDTH / 2} cy={height - 16} rx={SVG_WIDTH * .36} ry="27" />

          {paths.map(({ link, width, d }) => {
            const gradientId = `flow-${link.id.replace(/[^a-z0-9]/gi, "-")}`;
            const active = activeLink?.id === link.id;
            return (
              <g key={link.id} className={`sankey-flow-group${active ? " active" : ""}`}>
                <path className="sankey-flow-shadow" d={d} strokeWidth={Math.max(width + 8, 8)} />
                <path className="sankey-flow" d={d} stroke={`url(#${gradientId})`} strokeWidth={Math.max(width, .9)} filter="url(#sankey-glow)" />
                <path className="sankey-flow-specular" d={d} strokeWidth={Math.max(width * .16, .8)} />
                <path
                  className="sankey-flow-hit"
                  d={d}
                  strokeWidth={Math.max(width, 18)}
                  tabIndex={0}
                  role="button"
                  aria-label={`${link.label}: ${formatMoney(link.amount, data.currency)}`}
                  onMouseEnter={() => setHoveredId(link.id)}
                  onMouseLeave={() => setHoveredId(null)}
                  onFocus={() => setHoveredId(link.id)}
                  onBlur={() => setHoveredId(null)}
                  onClick={() => setSelectedId(link.id)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      setSelectedId(link.id);
                    }
                  }}
                >
                  <title>{link.label}: {formatMoney(link.amount, data.currency)}</title>
                </path>
              </g>
            );
          })}

          {leftNodes.map((node, index) => (
            <g key={node.id} className={`sankey-node sankey-node-${node.kind}`} transform={`translate(${LEFT_X} ${leftY[index] - NODE_HEIGHT / 2})`}>
              <rect className="sankey-node-shadow" x="3" y="7" width={NODE_WIDTH} height={NODE_HEIGHT} rx="19" />
              <rect className="sankey-node-body" width={NODE_WIDTH} height={NODE_HEIGHT} rx="19" />
              <path className="sankey-node-specular" d={`M 18 7 H ${NODE_WIDTH - 24}`} />
              <text className="sankey-node-label" x="16" y="20">{node.label}</text>
              <text className="sankey-node-amount" x="16" y="38">{formatMoney(node.amount, data.currency)}</text>
            </g>
          ))}

          <g className="sankey-hub" transform={`translate(${HUB_X} ${hubCenter - FLOW_BAND / 2 - 15})`}>
            <rect className="sankey-hub-shadow" x="5" y="9" width={HUB_WIDTH} height={FLOW_BAND + 30} rx="30" />
            <rect className="sankey-hub-body" width={HUB_WIDTH} height={FLOW_BAND + 30} rx="30" fill="url(#sankey-hub)" />
            <path className="sankey-hub-specular" d={`M 22 10 Q ${HUB_WIDTH / 2} 3 ${HUB_WIDTH - 20} 12`} />
            <text className="sankey-hub-label" x={HUB_WIDTH / 2} y={(FLOW_BAND + 30) / 2 - 5} textAnchor="middle">CASH</text>
            <text className="sankey-hub-label" x={HUB_WIDTH / 2} y={(FLOW_BAND + 30) / 2 + 10} textAnchor="middle">FLOW</text>
          </g>

          {rightNodes.map((node, index) => (
            <g key={node.id} className={`sankey-node sankey-node-${node.kind}`} transform={`translate(${RIGHT_X} ${rightY[index] - NODE_HEIGHT / 2})`}>
              <rect className="sankey-node-shadow" x="3" y="7" width={NODE_WIDTH} height={NODE_HEIGHT} rx="19" />
              <rect className="sankey-node-body" width={NODE_WIDTH} height={NODE_HEIGHT} rx="19" />
              <path className="sankey-node-specular" d={`M 18 7 H ${NODE_WIDTH - 24}`} />
              <text className="sankey-node-label" x="16" y="20">{node.label}</text>
              <text className="sankey-node-amount" x="16" y="38">{formatMoney(node.amount, data.currency)}</text>
            </g>
          ))}
        </svg>
        <span className="sr-only">{hub.label}</span>
      </div>

      {activeLink && !condensed && (
        <div className="sankey-inspector" aria-live="polite">
          <div>
            <span className={`sankey-kind sankey-kind-${activeLink.kind}`}>{activeLink.kind.replace("_", " ")}</span>
            <strong>{activeLink.label}</strong>
            <small>{comparisonText(activeNode) ?? `${activeLink.transaction_count.toLocaleString()} transaction${activeLink.transaction_count === 1 ? "" : "s"}`}</small>
          </div>
          <div className="sankey-inspector-value">
            <strong>{formatMoney(activeLink.amount, data.currency)}</strong>
            {share && <span>{Number.parseFloat(share).toFixed(1)}% of mapped cash</span>}
          </div>
          <div className="sankey-inspector-actions">
            {transactionUrl && <Link className="button secondary" to={transactionUrl}>View transactions</Link>}
            <button className="button secondary" type="button" onClick={() => onAsk(`Explain my ${activeLink.label} cash flow of ${formatMoney(activeLink.amount, data.currency)} during ${data.period.label}. What stands out and what should I do next?`)}>Ask Budget</button>
          </div>
        </div>
      )}
    </div>
  );
}

function CashFlowSummaryStrip({ data }: { data: CashFlowSankeyData }) {
  return (
    <div className="cash-flow-summary-strip">
      <div><span>Cash in</span><strong>{formatMoney(data.summary.inflow, data.currency)}</strong></div>
      <div><span>Outflows</span><strong>{formatMoney(data.summary.spending, data.currency)}</strong></div>
      <div><span>Net</span><strong className={numberFromMoney(data.summary.net_cash_flow) >= 0 ? "positive" : "negative"}>{formatMoney(data.summary.net_cash_flow, data.currency, { showSign: true })}</strong></div>
      <div><span>Savings rate</span><strong>{formatPercent(data.summary.savings_rate)}</strong></div>
    </div>
  );
}

export function CashFlowSankeyWidget({
  dashboard,
  size,
  onAsk,
}: {
  dashboard: DashboardData;
  size: DashboardCardSize;
  onAsk: (prompt: string) => void;
}) {
  const [range, setRange] = useState<CashFlowRange>("month");
  const [year, setYear] = useState(Number.parseInt(dashboard.period.month.slice(0, 4), 10));
  const [customStart, setCustomStart] = useState(dashboard.period.start);
  const [customEnd, setCustomEnd] = useState(dashboard.period.end);

  const search = useMemo(() => {
    const params = new URLSearchParams({ range });
    if (range === "month") params.set("month", dashboard.period.month);
    if (range === "year") params.set("year", String(year));
    if (range === "custom") {
      params.set("start_date", customStart);
      params.set("end_date", customEnd);
    }
    return params.toString();
  }, [range, dashboard.period.month, year, customStart, customEnd]);
  const customValid = range !== "custom" || (Boolean(customStart) && Boolean(customEnd) && customStart <= customEnd);
  const query = useQuery({
    queryKey: queryKeys.cashFlow(search),
    queryFn: () => apiRequest<CashFlowSankeyData>(`/cash-flow?${search}`),
    enabled: size !== "compact" && customValid,
  });

  if (size === "compact") {
    return (
      <section className="panel dashboard-fill-card cash-flow-widget cash-flow-widget-compact">
        <div className="panel-heading"><div><span className="eyebrow">Cash flow</span><h2>{formatMoney(dashboard.summary.net_cash_flow, dashboard.currency, { showSign: true })}</h2></div></div>
        <div className="cash-flow-compact-grid">
          <span><small>Income</small><strong>{formatMoney(dashboard.summary.income, dashboard.currency)}</strong></span>
          <span><small>Spending</small><strong>{formatMoney(dashboard.summary.spending, dashboard.currency)}</strong></span>
        </div>
        <button className="metric-ask" type="button" onClick={() => onAsk("Explain my cash flow this month and what I should focus on next.")}>Ask Budget</button>
      </section>
    );
  }

  return (
    <section className="panel dashboard-fill-card cash-flow-widget">
      <div className="panel-heading cash-flow-widget-heading">
        <div><span className="eyebrow">Flow intelligence</span><h2>{size === "hero" ? "Cash flow map" : "Cash flow"}</h2><p>{query.data?.period.label ?? dashboard.period.month}</p></div>
        {size === "hero" && (
          <div className="cash-flow-range-controls" aria-label="Cash flow range">
            <div className="cash-flow-range-tabs">
              {(["month", "year", "custom"] as const).map((option) => <button key={option} className={range === option ? "active" : ""} type="button" onClick={() => setRange(option)}>{option}</button>)}
            </div>
            {range === "year" && <label><span className="sr-only">Cash flow year</span><input type="number" min="2000" max="2100" value={year} onChange={(event) => setYear(Number(event.target.value) || year)} /></label>}
            {range === "custom" && <div className="cash-flow-custom-dates"><label><span className="sr-only">Cash flow start date</span><input type="date" value={customStart} onChange={(event) => setCustomStart(event.target.value)} /></label><span aria-hidden="true">→</span><label><span className="sr-only">Cash flow end date</span><input type="date" value={customEnd} onChange={(event) => setCustomEnd(event.target.value)} /></label></div>}
          </div>
        )}
      </div>
      {!customValid && <div className="inline-alert" role="alert">Choose an end date on or after the start date.</div>}
      {query.isPending && customValid && <LoadingState label="Mapping cash flow" />}
      {query.isError && <ErrorState message="Cash flow could not be mapped." onRetry={() => void query.refetch()} />}
      {query.data && <><CashFlowSummaryStrip data={query.data} /><SankeyGraphic data={query.data} condensed={size === "standard"} onAsk={onAsk} /><div className="cash-flow-footnote"><span>{query.data.summary.transaction_count.toLocaleString()} mapped transactions</span><span>{query.data.summary.excluded_transfer_count.toLocaleString()} transfers/exclusions omitted</span></div></>}
    </section>
  );
}
