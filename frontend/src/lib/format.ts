export function numberFromMoney(value: string | number | null | undefined): number {
  const parsed = typeof value === "number" ? value : Number.parseFloat(value ?? "0");
  return Number.isFinite(parsed) ? parsed : 0;
}

export function formatMoney(
  value: string | number,
  currency: string,
  options: { showSign?: boolean; maximumFractionDigits?: number } = {},
): string {
  const amount = numberFromMoney(value);
  try {
    return new Intl.NumberFormat(undefined, {
      style: "currency",
      currency,
      currencyDisplay: "narrowSymbol",
      signDisplay: options.showSign ? "exceptZero" : "auto",
      maximumFractionDigits: options.maximumFractionDigits ?? 2,
    }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
}

export function formatPercent(value: string | null): string {
  if (value === null) return "—";
  const amount = numberFromMoney(value);
  return new Intl.NumberFormat(undefined, {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(amount / 100);
}

export function formatDate(value: string, includeYear = false): string {
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    ...(includeYear ? { year: "numeric" } : {}),
  }).format(new Date(year, month - 1, day));
}

export function formatDateTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return value;
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

export function maskAccount(mask: string | null | undefined): string {
  if (!mask) return "••••";
  const digits = mask.replace(/\D/g, "").slice(-4);
  return digits ? `•••• ${digits.padStart(4, "•")}` : "••••";
}

export function monthLabel(month: string): string {
  const [year, monthNumber] = month.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(
    new Date(year, monthNumber - 1, 1),
  );
}

export function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}
