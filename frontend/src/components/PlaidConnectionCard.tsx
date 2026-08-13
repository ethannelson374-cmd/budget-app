import type { PlaidConnection } from "../api/types";
import { formatDateTime, formatMoney, maskAccount } from "../lib/format";

export function PlaidConnectionCard({
  connection,
  busy,
  onDisconnect,
}: {
  connection: PlaidConnection;
  busy: boolean;
  onDisconnect: (connection: PlaidConnection) => void;
}) {
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
        <span className={`connection-status ${connection.status}`}>{connection.status}</span>
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
        <span>{connection.last_synced_at ? `Balances updated ${formatDateTime(connection.last_synced_at)}` : "Connected"}</span>
        <button className="button danger" type="button" disabled={busy} onClick={() => onDisconnect(connection)}>
          {busy ? "Disconnecting…" : "Disconnect"}
        </button>
      </footer>
    </article>
  );
}
