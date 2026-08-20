import { useMemo, useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type {
  TrendCashFlowPoint,
  TrendRangeKey,
  TrendsView,
} from "../api/types";
import { PageHeader } from "../components/PageHeader";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { formatDate, formatMoney, formatPercent, numberFromMoney } from "../lib/format";

const ranges: Array<{ key: TrendRangeKey; label: string }> = [
  { key: "30d", label: "30D" },
  { key: "3m", label: "3M" },
  { key: "6m", label: "6M" },
  { key: "ytd", label: "YTD" },
  { key: "1y", label: "1Y" },
  { key: "all", label: "All" },
];

function tone(value: string | null) {
  if (value === null) return "neutral";
  const amount = numberFromMoney(value);
  if (amount > 0) return "positive";
  if (amount < 0) return "negative";
  return "neutral";
}

function deltaText(amount: string, percent: string | null, currency: string) {
  const formatted = formatMoney(amount, currency, { showSign: true });
  return percent === null ? formatted : `${formatted} · ${formatPercent(percent)}`;
}

function NetWorthTerrain({ data }: { data: TrendsView }) {
  const [selected, setSelected] = useState<number | null>(null);
  const rows = data.net_worth_history;
  const geometry = useMemo(() => {
    const width = 1040;
    const height = 390;
    const left = 58;
    const right = 28;
    const top = 34;
    const bottom = 62;
    const plotWidth = width - left - right;
    const plotHeight = height - top - bottom;
    const values = rows.map((row) => numberFromMoney(row.net_worth));
    const minimum = values.length ? Math.min(...values) : 0;
    const maximum = values.length ? Math.max(...values) : 1;
    const spread = Math.max(maximum - minimum, Math.max(Math.abs(maximum), 1) * 0.08, 1);
    const low = minimum - spread * 0.16;
    const high = maximum + spread * 0.14;
    const points = rows.map((row, index) => ({
      row,
      x: left + (rows.length <= 1 ? plotWidth / 2 : (index / (rows.length - 1)) * plotWidth),
      y: top + ((high - numberFromMoney(row.net_worth)) / (high - low)) * plotHeight,
    }));
    const line = points.length ? `M ${points.map((point) => `${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" L ")}` : "";
    const baseline = top + plotHeight;
    const area = points.length ? `${line} L ${points.at(-1)!.x.toFixed(2)} ${baseline} L ${points[0].x.toFixed(2)} ${baseline} Z` : "";
    return { width, height, left, right, top, bottom, plotHeight, baseline, points, line, area };
  }, [rows]);

  if (!rows.length) return <EmptyState title="No net-worth history yet" message="Budget will build a daily financial history as reporting snapshots are captured." />;

  const active = geometry.points[selected ?? geometry.points.length - 1];
  return (
    <div className="trend-terrain-wrap">
      <svg className="trend-terrain" viewBox={`0 0 ${geometry.width} ${geometry.height}`} role="img" aria-label="Net worth history terrain">
        <defs>
          <linearGradient id="trend-ridge" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor="#49f4e2" />
            <stop offset="48%" stopColor="#57a8ff" />
            <stop offset="100%" stopColor="#9a6cff" />
          </linearGradient>
          <linearGradient id="trend-area" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#63e9ff" stopOpacity=".42" />
            <stop offset="58%" stopColor="#5669ff" stopOpacity=".13" />
            <stop offset="100%" stopColor="#8b59ff" stopOpacity="0" />
          </linearGradient>
          <radialGradient id="trend-orb" cx="32%" cy="22%" r="72%">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="20%" stopColor="#8ffcf1" />
            <stop offset="58%" stopColor="#5caeff" />
            <stop offset="100%" stopColor="#7658ff" />
          </radialGradient>
          <filter id="trend-glow" x="-40%" y="-60%" width="180%" height="220%">
            <feGaussianBlur stdDeviation="7" result="blur" />
            <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
        </defs>
        {[0.2, 0.4, 0.6, 0.8].map((ratio) => {
          const y = geometry.top + geometry.plotHeight * ratio;
          return <line key={ratio} className="trend-grid-line" x1={geometry.left} x2={geometry.width - geometry.right} y1={y} y2={y} />;
        })}
        {geometry.points.map((point) => <line key={`wire-${point.row.date}`} className="trend-wire" x1={point.x} x2={point.x} y1={point.y} y2={geometry.baseline} />)}
        <path className="trend-terrain-shadow" d={geometry.line} transform="translate(0 13)" />
        <path className="trend-terrain-area" d={geometry.area} fill="url(#trend-area)" />
        <path className="trend-terrain-ridge" d={geometry.line} stroke="url(#trend-ridge)" filter="url(#trend-glow)" />
        <path className="trend-terrain-specular" d={geometry.line} transform="translate(0 -1.5)" />
        {geometry.points.map((point, index) => (
          <g key={point.row.date} className={`trend-point${selected === index ? " active" : ""}`}>
            <circle className="trend-point-shadow" cx={point.x + 2} cy={point.y + 7} r="8" />
            <circle
              className="trend-point-orb"
              cx={point.x}
              cy={point.y}
              r={selected === index ? 8 : 6}
              fill="url(#trend-orb)"
              tabIndex={0}
              role="button"
              aria-label={`${formatDate(point.row.date, true)} net worth ${formatMoney(point.row.net_worth, data.currency)}`}
              onMouseEnter={() => setSelected(index)}
              onFocus={() => setSelected(index)}
              onClick={() => setSelected(index)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  setSelected(index);
                }
              }}
            />
          </g>
        ))}
        <text className="trend-axis-label" x={geometry.left} y={geometry.height - 20}>{formatDate(rows[0].date, true)}</text>
        <text className="trend-axis-label" x={geometry.width - geometry.right} y={geometry.height - 20} textAnchor="end">{formatDate(rows.at(-1)!.date, true)}</text>
      </svg>
      {active && (
        <div className="trend-terrain-inspector" aria-live="polite">
          <div><span>Selected point</span><strong>{formatDate(active.row.date, true)}</strong></div>
          <div><span>Net worth</span><strong>{formatMoney(active.row.net_worth, data.currency)}</strong></div>
          <div><span>Cash available</span><strong>{formatMoney(active.row.cash_available, data.currency)}</strong></div>
          <div><span>Tracked debt</span><strong>{formatMoney(active.row.total_debt, data.currency)}</strong></div>
          <Link className="button secondary" to="/advisor" state={{ prompt: `Analyze my net worth of ${formatMoney(active.row.net_worth, data.currency)} on ${formatDate(active.row.date, true)}. What does the trend around this point tell me?` }}>Ask Budget</Link>
        </div>
      )}
    </div>
  );
}

function Composition({ data }: { data: TrendsView }) {
  const total = Math.max(1, ...data.composition.map((row) => numberFromMoney(row.value)));
  if (!data.composition.length) return <EmptyState title="No balance composition yet" message="Add accounts to see how assets and liabilities shape your net worth." />;
  return (
    <div className="trend-composition-list">
      {data.composition.map((row) => (
        <div className={`trend-composition-row ${row.kind}`} key={row.key}>
          <div><strong>{row.label}</strong><span>{row.account_count} account{row.account_count === 1 ? "" : "s"}</span></div>
          <div className="trend-composition-track"><span style={{ width: `${Math.max(5, numberFromMoney(row.value) / total * 100)}%` }} /></div>
          <div><strong>{formatMoney(row.value, data.currency)}</strong><span>{row.share_percent ? formatPercent(row.share_percent) : "—"}</span></div>
        </div>
      ))}
    </div>
  );
}

function AccountMomentum({ data }: { data: TrendsView }) {
  if (!data.account_contributions.length) return <EmptyState title="No account contribution data" message="Connected and manual accounts will appear here." />;
  const maximum = Math.max(1, ...data.account_contributions.map((row) => Math.abs(numberFromMoney(row.change_amount))));
  return (
    <div className="trend-account-list">
      {data.account_contributions.slice(0, 8).map((row) => {
        const value = numberFromMoney(row.change_amount);
        const url = new URLSearchParams({ account_id: String(row.account_id), start_date: data.period.start, end_date: data.period.end, sort: "date", direction: "desc" });
        return (
          <article key={row.account_id} className="trend-account-row">
            <div><strong>{row.name}</strong><span>{row.institution ?? row.account_type}</span></div>
            <div className="trend-account-meter"><span className={tone(row.change_amount)} style={{ width: `${row.history_available ? Math.max(4, Math.abs(value) / maximum * 100) : 0}%` }} /></div>
            <div className="trend-account-value">
              <strong>{formatMoney(row.current_balance, data.currency)}</strong>
              <span className={tone(row.change_amount)}>{row.history_available && row.change_amount !== null ? deltaText(row.change_amount, row.change_percent, data.currency) : "Building history"}</span>
            </div>
            <Link className="text-link" to={`/transactions?${url.toString()}`}>Activity →</Link>
          </article>
        );
      })}
    </div>
  );
}

function CashFlowTrend({ rows, currency }: { rows: TrendCashFlowPoint[]; currency: string }) {
  if (!rows.length) return <EmptyState title="No cash-flow trend in this range" message="Income and spending will appear as transactions accumulate." />;
  const maximum = Math.max(1, ...rows.flatMap((row) => [numberFromMoney(row.income), numberFromMoney(row.spending)]));
  return (
    <div className="trend-cashflow-chart" style={{ "--trend-columns": rows.length } as CSSProperties}>
      {rows.map((row) => (
        <div className="trend-cashflow-column" key={row.period}>
          <div className="trend-cashflow-bars">
            <span className="trend-bar income" style={{ height: `${Math.max(numberFromMoney(row.income) > 0 ? 7 : 0, numberFromMoney(row.income) / maximum * 100)}%` }} title={`Income ${formatMoney(row.income, currency)}`} />
            <span className="trend-bar spending" style={{ height: `${Math.max(numberFromMoney(row.spending) > 0 ? 7 : 0, numberFromMoney(row.spending) / maximum * 100)}%` }} title={`Spending ${formatMoney(row.spending, currency)}`} />
          </div>
          <small>{row.period.length === 10 ? formatDate(row.period) : row.period}</small>
        </div>
      ))}
    </div>
  );
}

function SpendingMomentum({ data }: { data: TrendsView }) {
  if (!data.spending_categories.length) return <EmptyState title="No spending momentum yet" message="Budget compares this range with the immediately preceding range." />;
  return (
    <div className="trend-momentum-list">
      {data.spending_categories.map((row) => {
        const search = new URLSearchParams({ start_date: data.period.start, end_date: data.period.end, kind: "expense", sort: "date", direction: "desc" });
        if (row.category_id) search.set("category_id", String(row.category_id));
        return (
          <Link key={row.key} to={`/transactions?${search.toString()}`} className="trend-momentum-row">
            <div><strong>{row.label}</strong><span>{row.share_percent ? `${formatPercent(row.share_percent)} of spending` : "Current range"}</span></div>
            <div><strong>{formatMoney(row.current, data.currency)}</strong><span className={tone(numberFromMoney(row.change_amount) <= 0 ? "1" : "-1")}>{row.change_percent === null ? "No prior baseline" : `${numberFromMoney(row.change_amount) > 0 ? "+" : ""}${formatPercent(row.change_percent)}`}</span></div>
          </Link>
        );
      })}
    </div>
  );
}

export function TrendsPage({ embedded = false }: { embedded?: boolean } = {}) {
  const [range, setRange] = useState<TrendRangeKey>("6m");
  const query = useQuery({ queryKey: queryKeys.trends(range), queryFn: () => apiRequest<TrendsView>(`/trends?range=${range}`) });

  if (query.isPending) return <div className={`page-container${embedded ? " embedded-page" : ""}`}><PageHeader title="Trends" description="Watch the shape of your finances change over time." /><LoadingState label="Building financial terrain" /></div>;
  if (query.isError || !query.data) return <div className={`page-container${embedded ? " embedded-page" : ""}`}><PageHeader title="Trends" description="Watch the shape of your finances change over time." /><ErrorState message="Financial trends could not be loaded." onRetry={() => void query.refetch()} /></div>;

  const data = query.data;
  return (
    <div className={`page-container trends-page${embedded ? " embedded-page" : ""}`}>
      <PageHeader
        title="Trends"
        description="Net worth, account momentum, income, and spending—without flattening the story into a spreadsheet."
        actions={<div className="trend-range-tabs" aria-label="Trend range">{ranges.map((item) => <button key={item.key} className={range === item.key ? "active" : ""} type="button" onClick={() => setRange(item.key)}>{item.label}</button>)}</div>}
      />

      <section className="trends-summary-grid" aria-label="Trend summary">
        <article className="panel trend-summary-card featured"><span>Net worth</span><strong>{formatMoney(data.summary.net_worth, data.currency)}</strong><small className={tone(data.summary.change_amount)}>{deltaText(data.summary.change_amount, data.summary.change_percent, data.currency)} · {data.period.label}</small></article>
        <article className="panel trend-summary-card"><span>Assets</span><strong>{formatMoney(data.summary.assets, data.currency)}</strong><small>Positive account balances</small></article>
        <article className="panel trend-summary-card"><span>Liabilities</span><strong>{formatMoney(data.summary.liabilities, data.currency)}</strong><small>Negative account balances</small></article>
        <article className="panel trend-summary-card"><span>YTD movement</span><strong className={tone(data.summary.ytd_change_amount)}>{formatMoney(data.summary.ytd_change_amount, data.currency, { showSign: true })}</strong><small>{data.summary.ytd_change_percent ? formatPercent(data.summary.ytd_change_percent) : "Building baseline"}</small></article>
      </section>

      <section className="panel trend-hero-panel">
        <div className="panel-heading trend-panel-heading"><div><span className="eyebrow">Financial terrain</span><h2>Net worth history</h2><p>{data.period.label}</p></div><Link className="button secondary" to="/advisor" state={{ prompt: `Analyze my net worth trend over ${data.period.label}. What improved, what worsened, and what should I focus on next?` }}>Ask Budget</Link></div>
        <NetWorthTerrain data={data} />
      </section>

      <div className="trends-two-column">
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Current structure</span><h2>Balance composition</h2></div></div><Composition data={data} /></section>
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Income quality</span><h2>Income signal</h2></div></div><div className="trend-income-signal"><div><span>Average monthly income</span><strong>{formatMoney(data.summary.average_monthly_income, data.currency)}</strong></div><div><span>Variability</span><strong>{data.summary.income_variability_percent ? formatPercent(data.summary.income_variability_percent) : "Building baseline"}</strong></div></div><div className="trend-income-sources">{data.income_sources.map((row) => <div key={row.label}><span>{row.label}</span><strong>{formatMoney(row.current, data.currency)}</strong><small>{row.share_percent ? formatPercent(row.share_percent) : "—"}</small></div>)}</div></section>
      </div>

      <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Account movement</span><h2>Who moved your net worth</h2><p>Per-account tracking starts with Phase 5D snapshots; Budget will not invent history it never captured.</p></div></div><AccountMomentum data={data} />{!data.history.account_tracking_active && <div className="trend-history-note">Account-level history starts after the reporting snapshot worker captures its first Phase 5D snapshot.</div>}</section>

      <div className="trends-two-column trends-lower-grid">
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Cash-flow history</span><h2>Income vs spending</h2></div></div><CashFlowTrend rows={data.cash_flow} currency={data.currency} /></section>
        <section className="panel"><div className="panel-heading"><div><span className="eyebrow">Category momentum</span><h2>Where spending changed</h2></div></div><SpendingMomentum data={data} /></section>
      </div>
    </div>
  );
}
