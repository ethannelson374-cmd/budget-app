import type { AccountSummary, AccountType, AccountWritePayload } from "../api/types";

const accountTypes: Array<{ value: AccountType; label: string }> = [
  { value: "depository", label: "Checking / savings" },
  { value: "credit", label: "Credit card" },
  { value: "loan", label: "Loan" },
  { value: "investment", label: "Investment" },
  { value: "other", label: "Other" },
];

function optionalValue(data: FormData, key: string): string | null {
  const value = String(data.get(key) ?? "").trim();
  return value || null;
}

export function AccountEditor({
  account,
  defaultCurrency,
  busy,
  error,
  onSubmit,
  onCancel,
}: {
  account?: AccountSummary;
  defaultCurrency: string;
  busy: boolean;
  error: string | null;
  onSubmit: (payload: AccountWritePayload) => void;
  onCancel: () => void;
}) {
  const handleSubmit = (form: HTMLFormElement) => {
    const data = new FormData(form);
    onSubmit({
      name: String(data.get("name") ?? "").trim(),
      official_name: optionalValue(data, "official_name"),
      account_type: String(data.get("account_type")) as AccountType,
      account_subtype: optionalValue(data, "account_subtype"),
      current_balance: String(data.get("current_balance") ?? "0").trim(),
      available_balance: optionalValue(data, "available_balance"),
      credit_limit: optionalValue(data, "credit_limit"),
      currency: String(data.get("currency") ?? defaultCurrency).trim().toUpperCase(),
      mask_last4: optionalValue(data, "mask_last4"),
    });
  };

  return (
    <section className="panel record-editor" aria-labelledby="account-editor-heading">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Manual account</span>
          <h2 id="account-editor-heading">{account ? `Edit ${account.name}` : "Add an account"}</h2>
          <p>Manual accounts are editable here. Connected-bank accounts will stay provider-managed.</p>
        </div>
      </div>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <form className="form-stack" onSubmit={(event) => { event.preventDefault(); handleSubmit(event.currentTarget); }}>
        <div className="form-grid two-columns">
          <label>Name<input required maxLength={120} name="name" defaultValue={account?.name ?? ""} placeholder="Everyday Checking" /></label>
          <label>Official name <span className="optional">Optional</span><input maxLength={255} name="official_name" defaultValue={account?.official_name ?? ""} placeholder="Primary Checking Account" /></label>
          <label>Account type<select required name="account_type" defaultValue={account?.account_type ?? "depository"}>{accountTypes.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}</select></label>
          <label>Subtype <span className="optional">Optional</span><input maxLength={40} name="account_subtype" defaultValue={account?.account_subtype ?? ""} placeholder="checking, auto, brokerage…" /></label>
          <label>Current balance<input required inputMode="decimal" name="current_balance" defaultValue={account?.current_balance ?? "0.00"} /><small>Use a negative balance for debt or other liabilities.</small></label>
          <label>Available balance <span className="optional">Optional</span><input inputMode="decimal" name="available_balance" defaultValue={account?.available_balance ?? ""} placeholder="Leave blank if unavailable" /></label>
          <label>Credit limit <span className="optional">Optional</span><input inputMode="decimal" name="credit_limit" defaultValue={account?.credit_limit ?? ""} placeholder="8000.00" /></label>
          <label>Currency<input required minLength={3} maxLength={3} pattern="[A-Za-z]{3}" name="currency" defaultValue={account?.currency ?? defaultCurrency} /></label>
          <label>Last four digits <span className="optional">Optional</span><input inputMode="numeric" maxLength={4} pattern="[0-9]{4}" name="mask_last4" defaultValue={account?.mask?.replace(/\D/g, "").slice(-4) ?? ""} placeholder="1234" /></label>
        </div>
        <div className="form-actions end">
          <button className="button ghost" type="button" onClick={onCancel} disabled={busy}>Cancel</button>
          <button className="button primary" type="submit" disabled={busy}>{busy ? "Saving…" : account ? "Save changes" : "Add account"}</button>
        </div>
      </form>
    </section>
  );
}
