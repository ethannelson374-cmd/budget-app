import type { DailyCashFlow } from "../api/types";
import { formatDate, formatMoney, numberFromMoney } from "../lib/format";

const WIDTH = 720;
const HEIGHT = 230;
const PAD_X = 28;
const PAD_Y = 24;

export function CashFlowChart({ data, currency }: { data: DailyCashFlow[]; currency: string }) {
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

  return (
    <div className="cash-flow-chart">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-labelledby="cash-flow-title cash-flow-description">
        <title id="cash-flow-title">Daily net cash flow</title>
        <desc id="cash-flow-description">Net cash flow by day, ranging from {formatMoney(minimum, currency)} to {formatMoney(maximum, currency)}.</desc>
        <defs>
          <linearGradient id="cash-flow-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="var(--chart-line)" stopOpacity="0.28" />
            <stop offset="1" stopColor="var(--chart-line)" stopOpacity="0.02" />
          </linearGradient>
        </defs>
        <line className="chart-grid" x1={PAD_X} x2={WIDTH - PAD_X} y1={zeroY} y2={zeroY} />
        <polygon points={area} fill="url(#cash-flow-fill)" />
        <polyline className="chart-line" points={line} />
        {data.map((point, index) => (
          <circle key={point.date} className="chart-point" cx={x(index)} cy={y(values[index])} r="3">
            <title>{formatDate(point.date, true)}: {formatMoney(point.amount, currency, { showSign: true })}</title>
          </circle>
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
