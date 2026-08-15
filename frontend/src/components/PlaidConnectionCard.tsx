import type { PlaidConnection } from "../api/types";
import { formatDateTime, formatMoney, maskAccount } from "../lib/format";

function syncStatus(connection: PlaidConnection): string {
  if (connection.transactions_last_error_code) return "Transaction sync needs attention";
  if (!connection.transactions_last_synced_at) return "Transactions not synced yet";
  if (connection.transactions_update_status === "NOT_READY") return "Plaid is preparing transaction history";
  if (connection.transactions_update_status === "INITIAL_UPDATE_COMPLETE") return "Recent transaction history synced";
  if (connection.transactions_update_status === "HISTORICAL_UPDATE_COMPLETE") return "Transaction history synced";
  return `Transactions synced ${formatDateTime(connection.transactions_last_synced_at)}`;
}


function freshness(connection: PlaidConnection): { label: string; tone: "fresh" | "stale" | "never" } {
  const raw = connection.transactions_last_synced_at ?? connection.last_synced_at;
  if (!raw) return { label: "Not synced", tone: "never" };
  const ageHours = (Date.now() - new Date(raw).getTime()) / 3_600_000;
  return ageHours > 12 ? { label: "May be stale", tone: "stale" } : { label: "Fresh", tone: "fresh" };
}

export function PlaidConnectionCard({
  connection,
  syncBusy,
  disconnectBusy,
  onSync,
  onDisconnect,
}: {
  connection: PlaidConnection;
  syncBusy: boolean;
  disconnectBusy: boolean;
  onSync: (connection: PlaidConnection) => void;
  onDisconnect: (connection: PlaidConnection) => void;
}) {
  const freshnessState = freshness(connection);
  const logo = connection.institution.logo
    ? `data:image/png;base64,${connection.institution.logo}`
    : null;
  return (
    <article className="connection-card">
      <header className="connection-card-header">
        <div className="institution-identity">
          {logo ? <img className="institution-logo" src={logo} alt="" /> : <span className="institution-logo fallback" aria-hidden="true">$</span>}
          <div>
            <span className="eyebrow">Connected through Plaid</span>
            <h2>{connection.institution.name}</h2>
          </div>
        </div>
        <div className="connection-badges"><span className={`freshness-badge ${freshnessState.tone}`}>{freshnessState.label}</span><span className={`connection-status ${connection.status}`}>{connection.status}</span></div>
      </header>
      <div className="connection-account-list">
        {connection.accounts.map((account) => (
          <div className="connection-account-row" key={account.id}>
            <div>
              <strong>{account.name}</strong>
              <span>{maskAccount(account.mask) || account.account_subtype || account.account_type}</span>
            </div>
            <strong>{formatMoney(account.current_balance, account.currency)}</strong>
          </div>
        ))}
      </div>
      <footer className="connection-card-footer">
        <div className="connection-sync-copy">
          <span>{syncStatus(connection)}</span>
          {connection.last_synced_at && <span>Balances updated {formatDateTime(connection.last_synced_at)}</span>}
        </div>
        <div className="connection-actions">
          <button className="button secondary" type="button" disabled={syncBusy || disconnectBusy} onClick={() => onSync(connection)}>
            {syncBusy ? "Syncing…" : "Sync now"}
          </button>
          <button className="button danger" type="button" disabled={syncBusy || disconnectBusy} onClick={() => onDisconnect(connection)}>
            {disconnectBusy ? "Disconnecting…" : "Disconnect"}
          </button>
        </div>
      </footer>
    </article>
  );
}
