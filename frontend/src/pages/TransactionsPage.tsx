import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { AccountsResponse, CategorySelection, PaginatedTransactions, TransactionItem, TransactionWritePayload } from "../api/types";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { PageHeader } from "../components/PageHeader";
import { TransactionEditor } from "../components/TransactionEditor";
import { TransactionList } from "../components/TransactionList";
import { Icon } from "../components/Icon";

const allowedParams = ["start_date", "end_date", "account_id", "category_id", "search", "min_amount", "max_amount", "kind", "pending", "sort", "direction", "page_size"];

function mutationError(error: unknown): string {
  return error instanceof ApiError ? error.message : "The transaction could not be saved.";
}

export function TransactionsPage() {
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [editor, setEditor] = useState<TransactionItem | null | undefined>(undefined);
  const page = Math.max(1, Number.parseInt(searchParams.get("page") ?? "1", 10) || 1);
  const pageSize = Math.min(100, Math.max(1, Number.parseInt(searchParams.get("page_size") ?? "25", 10) || 25));
  const canonical = new URLSearchParams(searchParams);
  canonical.set("page", String(page));
  canonical.set("page_size", String(pageSize));
  if (!canonical.has("sort")) canonical.set("sort", "date");
  if (!canonical.has("direction")) canonical.set("direction", "desc");
  const search = canonical.toString();

  const transactions = useQuery({ queryKey: queryKeys.transactions(search), queryFn: () => apiRequest<PaginatedTransactions>(`/transactions?${search}`) });
  const accounts = useQuery({ queryKey: queryKeys.accounts, queryFn: () => apiRequest<AccountsResponse>("/accounts") });
  const categories = useQuery({ queryKey: queryKeys.categories, queryFn: () => apiRequest<CategorySelection>("/categories/selection") });

  const saveTransaction = useMutation({
    mutationFn: ({ id, payload }: { id?: number; payload: TransactionWritePayload }) => apiRequest<TransactionItem>(id ? `/transactions/${id}` : "/transactions", {
      method: id ? "PATCH" : "POST",
      body: JSON.stringify(payload),
    }),
    onSuccess: async () => {
      setEditor(undefined);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["transactions"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ]);
    },
  });

  const deleteTransaction = useMutation({
    mutationFn: (transaction: TransactionItem) => apiRequest<{ ok: boolean }>(`/transactions/${transaction.id}`, { method: "DELETE" }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["transactions"] }),
        queryClient.invalidateQueries({ queryKey: ["dashboard"] }),
      ]);
    },
  });

  const applyFilters = (form: HTMLFormElement) => {
    const data = new FormData(form);
    const next = new URLSearchParams();
    allowedParams.forEach((key) => {
      const value = data.get(key);
      if (typeof value === "string" && value) next.set(key, value);
    });
    next.set("page", "1");
    setSearchParams(next);
  };

  const goToPage = (nextPage: number) => {
    const next = new URLSearchParams(searchParams);
    next.set("page", String(nextPage));
    setSearchParams(next);
    document.getElementById("main-content")?.focus();
  };

  const requestDelete = (transaction: TransactionItem) => {
    const label = transaction.merchant || transaction.description;
    if (window.confirm(`Delete ${label}?`)) deleteTransaction.mutate(transaction);
  };

  const canAddTransaction = Boolean(accounts.data?.accounts.length);

  return (
    <div className="page-container">
      <PageHeader
        title="Transactions"
        description="Search, add, and maintain your manual financial activity."
        actions={<button className="button primary" type="button" disabled={!canAddTransaction} onClick={() => { saveTransaction.reset(); setEditor(null); }}>Add transaction</button>}
      />

      {editor !== undefined && accounts.data && categories.data && (
        <TransactionEditor
          key={editor?.id ?? "new-transaction"}
          transaction={editor ?? undefined}
          accounts={accounts.data.accounts}
          categories={categories.data.categories}
          busy={saveTransaction.isPending}
          error={saveTransaction.isError ? mutationError(saveTransaction.error) : null}
          onCancel={() => { saveTransaction.reset(); setEditor(undefined); }}
          onSubmit={(payload) => saveTransaction.mutate({ id: editor?.id, payload })}
        />
      )}

      {!accounts.isPending && accounts.data?.accounts.length === 0 && (
        <div className="info-banner">Add an account before creating transactions. <Link className="text-link" to="/accounts">Go to Accounts</Link></div>
      )}
      {deleteTransaction.isError && <ErrorState message={mutationError(deleteTransaction.error)} />}

      <form key={searchParams.toString()} className="filter-panel" aria-label="Transaction filters" onSubmit={(event) => { event.preventDefault(); applyFilters(event.currentTarget); }}>
        <label className="search-field"><span>Search</span><div><Icon name="search" /><input name="search" type="search" placeholder="Merchant or description" defaultValue={searchParams.get("search") ?? ""} /></div></label>
        <label><span>From</span><input name="start_date" type="date" defaultValue={searchParams.get("start_date") ?? ""} /></label>
        <label><span>To</span><input name="end_date" type="date" defaultValue={searchParams.get("end_date") ?? ""} /></label>
        <label><span>Account</span><select name="account_id" defaultValue={searchParams.get("account_id") ?? ""}><option value="">All accounts</option>{accounts.data?.accounts.map((account) => <option key={account.id} value={account.id}>{account.name}</option>)}</select></label>
        <label><span>Category</span><select name="category_id" defaultValue={searchParams.get("category_id") ?? ""}><option value="">All categories</option>{categories.data?.categories.filter((category) => category.enabled).map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
        <label><span>Type</span><select name="kind" defaultValue={searchParams.get("kind") ?? ""}><option value="">All types</option><option value="income">Income</option><option value="expense">Expense</option><option value="refund">Refund</option><option value="transfer">Transfer</option></select></label>
        <label><span>Status</span><select name="pending" defaultValue={searchParams.get("pending") ?? ""}><option value="">Any status</option><option value="false">Posted</option><option value="true">Pending</option></select></label>
        <label><span>Minimum amount</span><input name="min_amount" inputMode="decimal" placeholder="0.00" defaultValue={searchParams.get("min_amount") ?? ""} /></label>
        <label><span>Maximum amount</span><input name="max_amount" inputMode="decimal" placeholder="Any" defaultValue={searchParams.get("max_amount") ?? ""} /></label>
        <label><span>Sort by</span><select name="sort" defaultValue={searchParams.get("sort") ?? "date"}><option value="date">Date</option><option value="amount">Amount</option><option value="merchant">Merchant</option><option value="description">Description</option></select></label>
        <label><span>Direction</span><select name="direction" defaultValue={searchParams.get("direction") ?? "desc"}><option value="desc">Newest / highest first</option><option value="asc">Oldest / lowest first</option></select></label>
        <label><span>Rows</span><select name="page_size" defaultValue={String(pageSize)}><option value="10">10</option><option value="25">25</option><option value="50">50</option><option value="100">100</option></select></label>
        <div className="filter-actions"><button className="button ghost" type="button" onClick={() => setSearchParams({})}>Clear</button><button className="button primary" type="submit">Apply filters</button></div>
      </form>

      {transactions.isPending && <LoadingState label="Loading transactions" />}
      {transactions.isError && <ErrorState message="Transactions could not be loaded." onRetry={() => void transactions.refetch()} />}
      {transactions.data && (
        <section className="panel transactions-panel" aria-labelledby="results-heading">
          <div className="panel-heading"><div><span className="eyebrow">{transactions.data.total.toLocaleString()} results</span><h2 id="results-heading">Activity</h2></div></div>
          {transactions.data.items.length ? (
            <TransactionList
              transactions={transactions.data.items}
              onEdit={(item) => { saveTransaction.reset(); setEditor(item); }}
              onDelete={requestDelete}
            />
          ) : (
            <EmptyState title="No matching transactions" message={canAddTransaction ? "Try clearing filters or add a manual transaction." : "Add an account first, then record your financial activity."} action={canAddTransaction ? <button className="button secondary" type="button" onClick={() => setEditor(null)}>Add transaction</button> : undefined} />
          )}
          {transactions.data.pages > 1 && <nav className="pagination" aria-label="Transaction pages"><button className="button secondary" type="button" disabled={page <= 1} onClick={() => goToPage(page - 1)}>Previous</button><span>Page <strong>{page}</strong> of {transactions.data.pages}</span><button className="button secondary" type="button" disabled={page >= transactions.data.pages} onClick={() => goToPage(page + 1)}>Next</button></nav>}
        </section>
      )}
    </div>
  );
}
