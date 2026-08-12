import type { CategoryTotal } from "../api/types";
import { formatMoney, numberFromMoney } from "../lib/format";

export function CategoryBars({ categories, currency }: { categories: CategoryTotal[]; currency: string }) {
  if (categories.length === 0) return <p className="chart-empty">No category spending in this period.</p>;
  const maximum = Math.max(...categories.map((category) => Math.abs(numberFromMoney(category.amount))), 1);

  return (
    <div className="category-bars">
      {categories.map((category) => {
        const signedAmount = numberFromMoney(category.amount);
        const magnitude = Math.abs(signedAmount);
        return (
          <div className="category-row" key={category.key}>
            <div className="category-label"><span>{category.name}</span><strong className={signedAmount < 0 ? "positive" : undefined}>{formatMoney(category.amount, currency)}</strong></div>
            <div className="bar-track" aria-label={`${category.name}: ${formatMoney(category.amount, currency)}`} role="meter" aria-valuemin={0} aria-valuemax={maximum} aria-valuenow={magnitude}>
              <span className="bar-fill" style={{ width: `${Math.max((magnitude / maximum) * 100, 2)}%` }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
