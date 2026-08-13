import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ApiError, apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { AccountSummary, AccountsResponse, AccountWritePayload } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { AccountCard } from "../components/AccountCard";
import { AccountEditor } from "../components/AccountEditor";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { PageHeader } from "../components/PageHeader";

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "The account could not be saved.";
}

export function AccountsPage() {
  const queryClient = useQueryClient();
  const { user } = useAuth();
  const [editor, setEditor] = useState<AccountSummary | null | undefined>(undefined);
  const accounts = useQuery({ queryKey: queryKeys.accounts, queryFn: () => apiRequest<AccountsResponse>("/accounts") });

  const saveAccount = useMutation({
    mutationFn: ({ id, payload }: { id?: number; payload: AccountWritePayload }) => apiRequest<AccountSummary>(id ? `/accounts/${id}` : "/accounts", {
      method: id ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    }),
    onSuccess: async () => {
      setEditor(undefined);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["transactions"] }),
      ]);
    },
  });

  const deleteAccount = useMutation({
    mutationFn: (account: AccountSummary) => apiRequest<{ ok: boolean }>(`/accounts/${account.id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.accounts }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
        queryClient.invalidateQueries({ queryKey: ["transactions"] }),
      ]);
    },
  });

  const requestDelete = (account: AccountSummary) => {
    if (window.confirm(`Delete ${account.name}? Its manual transactions will also be deleted.`)) {
      deleteAccount.mutate(account);
    }
  };

  return (
    <div className="page-container">
      <PageHeader
        title="Accounts"
        description="Track manual accounts now; connected institutions arrive in the next Phase 2 step."
        actions={<button className="button primary" type="button" onClick={() => { saveAccount.reset(); setEditor(null); }}>Add account</button>}
      />

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
      {accounts.isPending && <LoadingState label="Loading accounts" />}
      {accounts.isError && <ErrorState message="Your accounts could not be loaded." onRetry={() => void accounts.refetch()} />}
      {accounts.data && (accounts.data.accounts.length ? (
        <div className="account-grid">
          {accounts.data.accounts.map((account) => (
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
          title="No accounts yet"
          message="Add your first manual account to start populating net worth, cash available, and transactions."
          action={<button className="button secondary" type="button" onClick={() => setEditor(null)}>Add your first account</button>}
        />
      ))}
    </div>
  );
}
