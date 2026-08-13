import type { AccountSummary } from "../api/types";
import { formatDateTime, formatMoney, maskAccount } from "../lib/format";

export function AccountCard({
  account,
  onEdit,
  onDelete,
}: {
  account: AccountSummary;
  onEdit?: (account: AccountSummary) => void;
  onDelete?: (account: AccountSummary) => void;
}) {
  const displayMask = maskAccount(account.mask);
  const editable = account.source_type === "manual";
  return (
    <article className="account-card">
      <div className="account-card-header">
        <div>
          <span className="eyebrow">{account.institution ?? (editable ? "Manual account" : "Connected account")}</span>
          <h2>{account.name}</h2>
          <p>{displayMask}</p>
        </div>
        <span className="account-type">{account.account_subtype || account.account_type}</span>
      </div>
      <div className="account-balance">
        <span>Current balance</span>
        <strong>{formatMoney(account.current_balance, account.currency)}</strong>
      </div>
      <footer>
        <span>{account.available_balance === null ? "Available balance unavailable" : `${formatMoney(account.available_balance, account.currency)} available`}</span>
        <span>{account.last_synced_at ? `Updated ${formatDateTime(account.last_synced_at)}` : editable ? "Manual balance" : "Not yet synchronized"}</span>
      </footer>
      {editable && (onEdit || onDelete) && (
        <div className="record-actions" aria-label={`Actions for ${account.name}`}>
          {onEdit && <button className="button ghost" type="button" onClick={() => onEdit(account)}>Edit</button>}
          {onDelete && <button className="button danger" type="button" onClick={() => onDelete(account)}>Delete</button>}
        </div>
      )}
    </article>
  );
}
