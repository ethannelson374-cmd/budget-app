import { formatMoney, numberFromMoney } from "../lib/format";

export function Amount({ value, currency, signed = false, className = "" }: { value: string | number; currency: string; signed?: boolean; className?: string }) {
  const amount = numberFromMoney(value);
  const tone = amount > 0 ? "positive" : amount < 0 ? "negative" : "neutral";
  return <span className={`amount ${tone} ${className}`.trim()}>{formatMoney(value, currency, { showSign: signed })}</span>;
}
