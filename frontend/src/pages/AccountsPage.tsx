import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { AccountsResponse } from "../api/types";
import { AccountCard } from "../components/AccountCard";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { PageHeader } from "../components/PageHeader";

export function AccountsPage() {
  const accounts = useQuery({ queryKey: queryKeys.accounts, queryFn: () => apiRequest<AccountsResponse>("/accounts") });
  return (
    <div className="page-container">
      <PageHeader title="Accounts" description="Balances are read-only in Phase 1." />
      {accounts.isPending && <LoadingState label="Loading accounts" />}
      {accounts.isError && <ErrorState message="Your accounts could not be loaded." onRetry={() => void accounts.refetch()} />}
      {accounts.data && (accounts.data.accounts.length ? <div className="account-grid">{accounts.data.accounts.map((account) => <AccountCard account={account} key={account.id} />)}</div> : <EmptyState title="No accounts yet" message="Connected and imported accounts will appear here in a later phase." />)}
    </div>
  );
}
