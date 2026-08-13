import type { Category, TransactionIntelligencePayload, TransactionItem, TransactionKind } from "../api/types";

function clean(value: FormDataEntryValue | null): string | null {
  const text = String(value ?? "").trim();
  return text || null;
}

export function TransactionIntelligenceEditor({
  transaction,
  categories,
  busy,
  error,
  onSubmit,
  onCancel,
}: {
  transaction: TransactionItem;
  categories: Category[];
  busy: boolean;
  error: string | null;
  onSubmit: (payload: TransactionIntelligencePayload) => void;
  onCancel: () => void;
}) {
  const submit = (form: HTMLFormElement) => {
    const data = new FormData(form);
    const category = clean(data.get("category_id"));
    const kind = clean(data.get("kind_override")) as TransactionKind | null;
    onSubmit({
      category_id: category ? Number(category) : null,
      display_merchant: clean(data.get("display_merchant")),
      kind_override: kind,
      excluded_from_spending: data.get("excluded_from_spending") === "on",
    });
  };

  return (
    <section className="panel record-editor intelligence-editor" aria-labelledby="intelligence-editor-heading">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Transaction intelligence</span>
          <h2 id="intelligence-editor-heading">Tune {transaction.merchant || transaction.description}</h2>
          <p>Overrides change how Budget interprets this transaction without replacing the original provider data.</p>
        </div>
      </div>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <form className="form-stack" onSubmit={(event) => { event.preventDefault(); submit(event.currentTarget); }}>
        <div className="form-grid two-columns">
          <label>
            Display merchant
            <input name="display_merchant" maxLength={160} defaultValue={transaction.display_merchant ?? ""} placeholder={transaction.provider_merchant ?? transaction.merchant ?? "Walmart"} />
            <small>Original: {transaction.provider_merchant || transaction.description}</small>
          </label>
          <label>
            Category
            <select name="category_id" defaultValue={transaction.category?.id !== transaction.provider_category?.id ? transaction.category?.id ?? "" : ""}>
              <option value="">Provider / uncategorized</option>
              {categories.filter((category) => category.enabled || category.id === transaction.category?.id).map((category) => (
                <option key={category.id} value={category.id}>{category.name}</option>
              ))}
            </select>
            <small>Provider: {transaction.provider_category?.name ?? "Uncategorized"}</small>
          </label>
          <label>
            Type
            <select name="kind_override" defaultValue={transaction.kind === (transaction.provider_kind ?? transaction.kind) ? "" : transaction.kind}>
              <option value="">Use provider type ({transaction.provider_kind ?? transaction.kind})</option>
              <option value="expense">Expense</option>
              <option value="income">Income</option>
              <option value="refund">Refund</option>
              <option value="transfer">Transfer</option>
            </select>
          </label>
          <label className="checkbox-row intelligence-checkbox">
            <input type="checkbox" name="excluded_from_spending" defaultChecked={transaction.excluded_from_spending} />
            <span><strong>Exclude from spending</strong><small>Keep it visible, but omit it from dashboard income/spending and recurring detection.</small></span>
          </label>
        </div>
        <div className="form-actions end">
          <button className="button ghost" type="button" disabled={busy} onClick={onCancel}>Cancel</button>
          <button className="button primary" type="submit" disabled={busy}>{busy ? "Saving…" : "Save interpretation"}</button>
        </div>
      </form>
    </section>
  );
}
