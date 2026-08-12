import type { TransactionItem } from "../api/types";
import { formatDate, formatMoney, numberFromMoney, maskAccount } from "../lib/format";

function transactionTone(transaction: TransactionItem): string {
  if (transaction.kind === "income" || transaction.kind === "refund") return "positive";
  if (transaction.kind === "expense") return "negative";
  return "neutral";
}

function displayAmount(transaction: TransactionItem): number {
  const amount = numberFromMoney(transaction.amount);
  return transaction.kind === "expense" && amount > 0 ? -amount : amount;
}

export function TransactionList({ transactions, compact = false }: { transactions: TransactionItem[]; compact?: boolean }) {
  return (
    <div className={`transaction-list${compact ? " compact" : ""}`}>
      {transactions.map((transaction) => (
        <article className="transaction-row" key={transaction.id}>
          <time dateTime={transaction.posted_date} className="transaction-date">{formatDate(transaction.posted_date)}</time>
          <div className="transaction-main">
            <strong>{transaction.merchant || transaction.description}</strong>
            <span>{transaction.category?.name ?? "Uncategorized"} · {transaction.account.name} {maskAccount(transaction.account.mask)}</span>
          </div>
          <div className="transaction-meta">
            <strong className={`amount ${transactionTone(transaction)}`}>{formatMoney(displayAmount(transaction), transaction.account.currency, { showSign: true })}</strong>
            <span>{transaction.pending ? "Pending" : transaction.kind.charAt(0).toUpperCase() + transaction.kind.slice(1)}</span>
          </div>
        </article>
      ))}
    </div>
  );
}
