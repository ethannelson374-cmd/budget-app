import type { AccountSummary } from "../api/types";
import { formatDateTime, formatMoney, maskAccount } from "../lib/format";

export function AccountCard({ account }: { account: AccountSummary }) {
  const displayMask = maskAccount(account.mask);
  return (
    <article className="account-card">
      <div className="account-card-header">
        <div>
          <span className="eyebrow">{account.institution ?? "Independent account"}</span>
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
        <span>{account.last_synced_at ? `Updated ${formatDateTime(account.last_synced_at)}` : "Not yet synchronized"}</span>
      </footer>
    </article>
  );
}
