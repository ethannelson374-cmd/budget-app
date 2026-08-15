import type { PlaidConnection } from "../api/types";
import { formatDateTime, formatMoney, maskAccount } from "../lib/format";

function syncStatus(connection: PlaidConnection): string {
  if (!connection.environment_matches) return "This test connection belongs to Plaid Sandbox";
  if (connection.update_reason === "ITEM_LOGIN_REQUIRED") return "Your bank needs you to sign in again";
  if (connection.update_reason === "PENDING_DISCONNECT" || connection.update_reason === "PENDING_EXPIRATION") return "Your bank authorization needs to be renewed";
  if (connection.update_reason === "NEW_ACCOUNTS_AVAILABLE") return "Your bank has additional accounts available to review";
  if (connection.update_reason === "USER_PERMISSION_REVOKED") return "Bank access was revoked and needs attention";
  if (connection.update_required || connection.status === "error") return "Your bank connection needs attention";
  if (connection.transactions_last_error_code) return "Transaction sync needs attention";
  if (!connection.transactions_last_synced_at) return "Transactions not synced yet";
  if (connection.transactions_update_status === "NOT_READY") return "Plaid is preparing transaction history";
  if (connection.transactions_update_status === "INITIAL_UPDATE_COMPLETE") return "Recent transaction history synced";
  if (connection.transactions_update_status === "HISTORICAL_UPDATE_COMPLETE") return "Transaction history synced";
  return `Transactions synced ${formatDateTime(connection.transactions_last_synced_at)}`;
}

function freshness(connection: PlaidConnection): { label: string; tone: "fresh" | "stale" | "never" } {
  if (!connection.environment_matches) return { label: "Test connection", tone: "never" };
  if (connection.health === "needs_attention") return { label: "Needs attention", tone: "stale" };
  const raw = connection.transactions_last_synced_at ?? connection.last_synced_at;
  if (!raw) return { label: "Not synced", tone: "never" };
  const ageHours = (Date.now() - new Date(raw).getTime()) / 3_600_000;
  return ageHours > 12 ? { label: "May be stale", tone: "stale" } : { label: "Fresh", tone: "fresh" };
}

function updateLabel(connection: PlaidConnection): string {
  if (connection.update_reason === "NEW_ACCOUNTS_AVAILABLE") return "Review accounts";
  if (connection.update_reason === "PENDING_DISCONNECT" || connection.update_reason === "PENDING_EXPIRATION") return "Renew access";
  return "Reconnect";
}

export function PlaidConnectionCard({
  connection,
  syncBusy,
  updateBusy,
  disconnectBusy,
  onSync,
  onUpdate,
  onDisconnect,
}: {
  connection: PlaidConnection;
  syncBusy: boolean;
  updateBusy: boolean;
  disconnectBusy: boolean;
  onSync: (connection: PlaidConnection) => void;
  onUpdate: (connection: PlaidConnection) => void;
  onDisconnect: (connection: PlaidConnection) => void;
}) {
  const freshnessState = freshness(connection);
  const logo = connection.institution.logo
    ? `data:image/png;base64,${connection.institution.logo}`
    : null;
  const busy = syncBusy || updateBusy || disconnectBusy;
  return (
    <article className={`connection-card ${connection.health !== "healthy" ? "needs-attention" : ""}`}>
      <header className="connection-card-header">
        <div className="institution-identity">
          {logo ? <img className="institution-logo" src={logo} alt="" /> : <span className="institution-logo fallback" aria-hidden="true">$</span>}
          <div>
            <span className="eyebrow">Connected through Plaid · {connection.environment === "production" ? "Production" : "Sandbox"}</span>
            <h2>{connection.institution.name}</h2>
          </div>
        </div>
        <div className="connection-badges">
          <span className={`freshness-badge ${freshnessState.tone}`}>{freshnessState.label}</span>
          <span className={`connection-status ${connection.health === "healthy" ? "active" : "error"}`}>
            {connection.health === "healthy" ? "Connected" : "Attention"}
          </span>
        </div>
      </header>

      {!connection.environment_matches && (
        <div className="inline-notice connection-attention">
          Sandbox Items cannot move into Plaid Production. Remove this test connection, then connect the real institution again.
        </div>
      )}
      {connection.environment_matches && connection.update_required && (
        <div className="inline-notice connection-attention">
          {syncStatus(connection)}.
        </div>
      )}

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
          {connection.consent_expiration_at && <span>Authorization expires {formatDateTime(connection.consent_expiration_at)}</span>}
        </div>
        <div className="connection-actions">
          {connection.environment_matches && connection.update_required && (
            <button className="button primary" type="button" disabled={busy} onClick={() => onUpdate(connection)}>
              {updateBusy ? "Opening…" : updateLabel(connection)}
            </button>
          )}
          <button className="button secondary" type="button" disabled={busy || !connection.environment_matches || connection.update_required} onClick={() => onSync(connection)}>
            {syncBusy ? "Syncing…" : "Sync now"}
          </button>
          <button className="button danger" type="button" disabled={busy} onClick={() => onDisconnect(connection)}>
            {disconnectBusy ? "Disconnecting…" : connection.environment_matches ? "Disconnect" : "Remove test connection"}
          </button>
        </div>
      </footer>
    </article>
  );
}
