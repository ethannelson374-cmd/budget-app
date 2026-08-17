import { useId } from "react";
import type { DailyCashFlow } from "../api/types";
import { formatDate, formatMoney, numberFromMoney } from "../lib/format";

const WIDTH = 720;
const HEIGHT = 230;
const PAD_X = 28;
const PAD_Y = 24;

export function CashFlowChart({ data, currency }: { data: DailyCashFlow[]; currency: string }) {
  const instanceId = useId().replaceAll(":", "");
  if (data.length === 0) return <p className="chart-empty">No cash flow activity in this period.</p>;

  const values = data.map((point) => numberFromMoney(point.amount));
  const maximum = Math.max(...values, 0);
  const minimum = Math.min(...values, 0);
  const range = maximum - minimum || 1;
  const chartWidth = WIDTH - PAD_X * 2;
  const chartHeight = HEIGHT - PAD_Y * 2;
  const x = (index: number) => PAD_X + (data.length === 1 ? chartWidth / 2 : (index / (data.length - 1)) * chartWidth);
  const y = (value: number) => PAD_Y + ((maximum - value) / range) * chartHeight;
  const zeroY = y(0);
  const line = values.map((value, index) => `${x(index)},${y(value)}`).join(" ");
  const area = `${PAD_X},${zeroY} ${line} ${x(data.length - 1)},${zeroY}`;
  const fillId = `cash-flow-fill-${instanceId}`;
  const lineId = `cash-flow-line-${instanceId}`;
  const pointId = `cash-flow-point-${instanceId}`;
  const glowId = `cash-flow-glow-${instanceId}`;

  return (
    <div className="cash-flow-chart">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-labelledby={`${instanceId}-title ${instanceId}-description`}>
        <title id={`${instanceId}-title`}>Daily net cash flow</title>
        <desc id={`${instanceId}-description`}>Net cash flow by day, ranging from {formatMoney(minimum, currency)} to {formatMoney(maximum, currency)}.</desc>
        <defs>
          <linearGradient id={fillId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--aurora-cyan)" stopOpacity="0.34" />
            <stop offset="0.55" stopColor="var(--aurora-blue)" stopOpacity="0.20" />
            <stop offset="1" stopColor="var(--aurora-violet)" stopOpacity="0.035" />
          </linearGradient>
          <linearGradient id={lineId} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stopColor="var(--aurora-cyan)" />
            <stop offset="0.55" stopColor="var(--aurora-blue)" />
            <stop offset="1" stopColor="var(--aurora-violet)" />
          </linearGradient>
          <radialGradient id={pointId} cx="32%" cy="24%" r="78%">
            <stop offset="0" stopColor="#ffffff" stopOpacity="0.98" />
            <stop offset="0.18" stopColor="var(--aurora-cyan)" stopOpacity="0.98" />
            <stop offset="0.62" stopColor="var(--aurora-blue)" stopOpacity="0.96" />
            <stop offset="1" stopColor="var(--aurora-violet)" stopOpacity="0.9" />
          </radialGradient>
          <filter id={glowId} x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="3.2" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
        <line className="chart-grid chart-grid-shadow" x1={PAD_X} x2={WIDTH - PAD_X} y1={zeroY + 2.5} y2={zeroY + 2.5} />
        <line className="chart-grid" x1={PAD_X} x2={WIDTH - PAD_X} y1={zeroY} y2={zeroY} />
        <polygon className="chart-area" points={area} fill={`url(#${fillId})`} />
        <polyline className="chart-line-shadow" points={line} />
        <polyline className="chart-line" points={line} stroke={`url(#${lineId})`} filter={`url(#${glowId})`} />
        <polyline className="chart-line-highlight" points={line} />
        {data.map((point, index) => (
          <g key={point.date} transform={`translate(${x(index)} ${y(values[index])})`}>
            <g className="chart-point-orb">
              <title>{formatDate(point.date, true)}: {formatMoney(point.amount, currency, { showSign: true })}</title>
              <circle className="chart-point-shadow" cx="0" cy="3.5" r="6.4" />
              <circle className="chart-point" cx="0" cy="0" r="5.3" fill={`url(#${pointId})`} />
              <circle className="chart-point-highlight" cx="-1.6" cy="-1.8" r="1.45" />
            </g>
          </g>
        ))}
      </svg>
      <div className="chart-axis" aria-hidden="true"><span>{formatDate(data[0].date)}</span><span>{formatDate(data[data.length - 1].date)}</span></div>
      <table className="sr-only">
        <caption>Daily net cash flow values</caption>
        <thead><tr><th>Date</th><th>Net cash flow</th></tr></thead>
        <tbody>{data.map((point) => <tr key={point.date}><td>{point.date}</td><td>{formatMoney(point.amount, currency)}</td></tr>)}</tbody>
      </table>
    </div>
  );
}
