import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type {
  AccountSummary,
  AccountsResponse,
  AccountWritePayload,
  PlaidConnection,
  PlaidConnectionsResponse,
  PlaidLinkTokenResponse,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { AccountCard } from "../components/AccountCard";
import { AccountEditor } from "../components/AccountEditor";
import { PlaidConnectionCard } from "../components/PlaidConnectionCard";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { PageHeader } from "../components/PageHeader";
import { createPlaidHandler, rememberPlaidLinkToken, clearPlaidLinkToken } from "../lib/plaid";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : error instanceof Error ? error.message : "The request could not be completed.";
}

export function AccountsPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [editor, setEditor] = useState<AccountSummary | null | undefined>(undefined);
  const [plaidError, setPlaidError] = useState<string | null>(null);
  const accounts = useQuery({ queryKey: queryKeys.accounts, queryFn: () => apiRequest<AccountsResponse>("/accounts") });
  const connections = useQuery({
    queryKey: queryKeys.plaidConnections,
    queryFn: () => apiRequest<PlaidConnectionsResponse>("/plaid/connections"),
  });

  const refreshFinancialData = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.accounts }),
      queryClient.invalidateQueries({ queryKey: queryKeys.plaidConnections }),
      queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      queryClient.invalidateQueries({ queryKey: ["transactions"] }),
    ]);
  };

  const saveAccount = useMutation({
    mutationFn: ({ id, payload }: { id?: number; payload: AccountWritePayload }) => apiRequest<AccountSummary>(id ? `/accounts/${id}` : "/accounts", {
      method: id ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    }),
    onSuccess: async () => {
      setEditor(undefined);
      await refreshFinancialData();
    },
  });

  const deleteAccount = useMutation({
    mutationFn: (account: AccountSummary) => apiRequest<{ ok: boolean }>(`/accounts/${account.id}`, { method: "DELETE" }),
    onSuccess: refreshFinancialData,
  });

  const exchangePlaid = useMutation({
    mutationFn: ({ publicToken, metadata }: { publicToken: string; metadata: PlaidLinkSuccessMetadata }) =>
      apiRequest<PlaidConnectionsResponse>("/plaid/exchange", {
        method: "POST",
        body: JSON.stringify({
          public_token: publicToken,
          institution_id: metadata.institution?.institution_id ?? null,
          accounts: metadata.accounts.map(({ name, mask }) => ({ name, mask })),
        }),
      }),
    onSuccess: async () => {
      clearPlaidLinkToken();
      setPlaidError(null);
      await refreshFinancialData();
    },
    onError: (error) => {
      clearPlaidLinkToken();
      setPlaidError(errorMessage(error));
    },
  });

  const connectPlaid = useMutation({
    mutationFn: () => apiRequest<PlaidLinkTokenResponse>("/plaid/link-token", { method: "POST" }),
    onSuccess: ({ link_token }) => {
      rememberPlaidLinkToken(link_token);
      setPlaidError(null);
      let handler: PlaidHandler | undefined;
      try {
        handler = createPlaidHandler({
          token: link_token,
          onSuccess: (publicToken, metadata) => {
            handler?.destroy();
            if (!publicToken) {
              clearPlaidLinkToken();
              setPlaidError("Plaid did not return a connection token.");
              return;
            }
            exchangePlaid.mutate({ publicToken, metadata });
          },
          onExit: (error) => {
            handler?.destroy();
            clearPlaidLinkToken();
            if (error) setPlaidError("The bank connection was not completed. Try again.");
          },
          onLoad: () => handler?.open(),
        });
      } catch (error) {
        clearPlaidLinkToken();
        setPlaidError(errorMessage(error));
      }
    },
    onError: (error) => setPlaidError(errorMessage(error)),
  });

  const disconnectPlaid = useMutation({
    mutationFn: (connection: PlaidConnection) => apiRequest<{ ok: boolean }>(`/plaid/connections/${connection.id}`, { method: "DELETE" }),
    onSuccess: refreshFinancialData,
  });

  const requestDelete = (account: AccountSummary) => {
    if (window.confirm(`Delete ${account.name}? Its manual transactions will also be deleted.`)) {
      deleteAccount.mutate(account);
    }
  };

  const requestDisconnect = (connection: PlaidConnection) => {
    if (window.confirm(`Disconnect ${connection.institution.name}? Its connected accounts will be removed from Budget.`)) {
      disconnectPlaid.mutate(connection);
    }
  };

  const manualAccounts = accounts.data?.accounts.filter((account) => account.source_type === "manual") ?? [];
  const plaidBusy = connectPlaid.isPending || exchangePlaid.isPending;
  const configured = connections.data?.configured ?? false;

  return (
    <div className="page-container">
      <PageHeader
        title="Accounts"
        description="Connect institutions through Plaid or keep accounts manually when automation is not available."
        actions={(
          <div className="page-actions">
            <button className="button secondary" type="button" disabled={!configured || plaidBusy} onClick={() => connectPlaid.mutate()}>
              {plaidBusy ? "Connecting…" : "Connect a bank"}
            </button>
            <button className="button primary" type="button" onClick={() => { saveAccount.reset(); setEditor(null); }}>Add manual account</button>
          </div>
        )}
      />

      {connections.isPending && <LoadingState label="Loading bank connections" />}
      {connections.isError && <ErrorState message="Your bank connections could not be loaded." onRetry={() => void connections.refetch()} />}
      {connections.data && !connections.data.configured && (
        <div className="inline-notice">Plaid is not configured on this server yet. Manual accounts are still available.</div>
      )}
      {plaidError && <ErrorState title="Bank connection issue" message={plaidError} />}
      {connections.data && connections.data.connections.length > 0 && (
        <section className="account-section" aria-labelledby="connected-institutions-title">
          <div className="section-heading">
            <div>
              <span className="eyebrow">Automatic</span>
              <h2 id="connected-institutions-title">Connected institutions</h2>
            </div>
            {connections.data.environment === "sandbox" && <span className="environment-badge">Sandbox</span>}
          </div>
          <div className="connection-grid">
            {connections.data.connections.map((connection) => (
              <PlaidConnectionCard
                key={connection.id}
                connection={connection}
                busy={disconnectPlaid.isPending && disconnectPlaid.variables?.id === connection.id}
                onDisconnect={requestDisconnect}
              />
            ))}
          </div>
        </section>
      )}

      <section className="account-section" aria-labelledby="manual-accounts-title">
        <div className="section-heading">
          <div>
            <span className="eyebrow">Manual</span>
            <h2 id="manual-accounts-title">Manual accounts</h2>
          </div>
        </div>

        {editor !== undefined && (
          <AccountEditor
            key={editor?.id ?? "new-account"}
            account={editor ?? undefined}
            defaultCurrency={user?.settings.currency ?? "USD"}
            busy={saveAccount.isPending}
            error={saveAccount.isError ? errorMessage(saveAccount.error) : null}
            onCancel={() => { saveAccount.reset(); setEditor(undefined); }}
            onSubmit={(payload) => saveAccount.mutate({ id: editor?.id, payload })}
          />
        )}

        {deleteAccount.isError && <ErrorState message={errorMessage(deleteAccount.error)} />}
        {disconnectPlaid.isError && <ErrorState message={errorMessage(disconnectPlaid.error)} />}
        {accounts.isPending && <LoadingState label="Loading accounts" />}
        {accounts.isError && <ErrorState message="Your accounts could not be loaded." onRetry={() => void accounts.refetch()} />}
        {accounts.data && (manualAccounts.length ? (
          <div className="account-grid">
            {manualAccounts.map((account) => (
              <AccountCard
                account={account}
                key={account.id}
                onEdit={(item) => { saveAccount.reset(); setEditor(item); }}
                onDelete={requestDelete}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            title="No manual accounts"
            message={connections.data?.connections.length ? "Your connected accounts are shown above. Add a manual account for anything Plaid cannot track." : "Add a manual account or connect a bank to start populating your financial picture."}
            action={<button className="button secondary" type="button" onClick={() => setEditor(null)}>Add a manual account</button>}
          />
        ))}
      </section>
    </div>
  );
}
