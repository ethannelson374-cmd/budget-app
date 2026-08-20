import type { AccountSummary, Category, TransactionItem, TransactionKind, TransactionWritePayload } from "../api/types";
import { normalizeMoneyInput } from "../lib/format";
import { MoneyInput } from "./MoneyInput";

function optionalValue(data: FormData, key: string): string | null {
  const value = String(data.get(key) ?? "").trim();
  return value || null;
}

function editableAmount(transaction?: TransactionItem): string {
  if (!transaction) return "";
  if (transaction.kind === "expense" && transaction.amount.startsWith("-")) return transaction.amount.slice(1);
  return transaction.amount;
}

function signedAmount(raw: string, kind: TransactionKind): string {
  const trimmed = normalizeMoneyInput(raw);
  const absolute = trimmed.replace(/^[+-]/, "");
  if (kind === "expense") return `-${absolute}`;
  if (kind === "income" || kind === "refund") return absolute;
  return trimmed;
}

function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

export function TransactionEditor({
  transaction,
  accounts,
  categories,
  busy,
  error,
  onSubmit,
  onCancel,
}: {
  transaction?: TransactionItem;
  accounts: AccountSummary[];
  categories: Category[];
  busy: boolean;
  error: string | null;
  onSubmit: (payload: TransactionWritePayload) => void;
  onCancel: () => void;
}) {
  const handleSubmit = (form: HTMLFormElement) => {
    const data = new FormData(form);
    const kind = String(data.get("kind")) as TransactionKind;
    onSubmit({
      account_id: Number(data.get("account_id")),
      category_id: optionalValue(data, "category_id") ? Number(data.get("category_id")) : null,
      posted_date: String(data.get("posted_date") ?? ""),
      authorized_date: optionalValue(data, "authorized_date"),
      merchant: optionalValue(data, "merchant"),
      description: String(data.get("description") ?? "").trim(),
      amount: signedAmount(String(data.get("amount") ?? ""), kind),
      kind,
      pending: data.get("pending") === "on",
      notes: optionalValue(data, "notes"),
    });
  };

  return (
    <section className="panel record-editor" aria-labelledby="transaction-editor-heading">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Manual transaction</span>
          <h2 id="transaction-editor-heading">{transaction ? "Edit transaction" : "Add a transaction"}</h2>
          <p>Expenses are stored as negative amounts; enter the expense amount normally and Budget handles the sign.</p>
        </div>
      </div>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <form className="form-stack" onSubmit={(event) => { event.preventDefault(); handleSubmit(event.currentTarget); }}>
        <div className="form-grid two-columns">
          <label>Account<select required name="account_id" defaultValue={transaction?.account.id ?? accounts[0]?.id ?? ""}>{accounts.map((account) => <option key={account.id} value={account.id}>{account.display_name}</option>)}</select></label>
          <label>Category<select name="category_id" defaultValue={transaction?.category?.id ?? ""}><option value="">Uncategorized</option>{categories.filter((category) => category.enabled || category.id === transaction?.category?.id).map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
          <label>Posted date<input required type="date" name="posted_date" defaultValue={transaction?.posted_date ?? localToday()} /></label>
          <label>Authorized date <span className="optional">Optional</span><input type="date" name="authorized_date" defaultValue={transaction?.authorized_date ?? ""} /></label>
          <label>Type<select required name="kind" defaultValue={transaction?.kind ?? "expense"}><option value="expense">Expense</option><option value="income">Income</option><option value="refund">Refund</option><option value="transfer">Transfer</option></select></label>
          <label>Amount<MoneyInput required name="amount" defaultValue={editableAmount(transaction)} placeholder="42.50" /><small>For transfers, use a negative amount when money leaves this account.</small></label>
          <label>Merchant <span className="optional">Optional</span><input maxLength={160} name="merchant" defaultValue={transaction?.merchant ?? ""} placeholder="Corner Market" /></label>
          <label>Description<input required maxLength={255} name="description" defaultValue={transaction?.description ?? ""} placeholder="Groceries" /></label>
        </div>
        <label>Notes <span className="optional">Optional</span><textarea maxLength={4000} name="notes" defaultValue={transaction?.notes ?? ""} rows={3} /></label>
        <label className="checkbox-row"><input type="checkbox" name="pending" defaultChecked={transaction?.pending ?? false} /><span>Pending transaction</span></label>
        <div className="form-actions end">
          <button className="button ghost" type="button" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="button primary" type="submit" disabled={busy}>{busy ? "Saving…" : transaction ? "Save changes" : "Add transaction"}</button>
        </div>
      </form>
    </section>
  );
}
