import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiDownload, apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { AccountsResponse, CsvTransactionImportResult } from "../api/types";

export function DataPrivacySettings() {
  const queryClient = useQueryClient();
  const accounts = useQuery({ queryKey: queryKeys.accounts, queryFn: () => apiRequest<AccountsResponse>("/accounts") });
  const manualAccounts = useMemo(() => accounts.data?.accounts.filter((account) => account.source_type === "manual") ?? [], [accounts.data]);
  const [accountId, setAccountId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const [password, setPassword] = useState("");

  const importCsv = useMutation({
    mutationFn: async () => {
      if (!file || !accountId) throw new ApiError("Choose a manual account and CSV file first.", { status: 422, code: "csv_import_incomplete" });
      if (file.size > 2_000_000) throw new ApiError("CSV imports are limited to 2 MB.", { status: 413, code: "csv_too_large" });
      const csv_text = await file.text();
      return apiRequest<CsvTransactionImportResult>("/privacy/import-transactions", {
        method: "POST",
        body: JSON.stringify({ account_id: Number(accountId), csv_text }),
      });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["transactions"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: queryKeys.recurring });
      void queryClient.invalidateQueries({ queryKey: ["reports"] });
    },
  });

  const deleteAccount = useMutation({
    mutationFn: () => apiRequest<{ ok: boolean }>("/auth/account", {
      method: "DELETE",
      body: JSON.stringify({ confirmation: "DELETE", password: password || null }),
    }),
    onSuccess: () => window.location.assign("/login"),
  });

  const download = async (path: string) => {
    setDownloadError(null);
    try {
      await apiDownload(path);
    } catch (error) {
      setDownloadError(error instanceof Error ? error.message : "The download could not be completed.");
    }
  };

  const submitImport = (event: FormEvent) => {
    event.preventDefault();
    importCsv.reset();
    importCsv.mutate();
  };

  const importError = importCsv.error instanceof ApiError ? importCsv.error.message : importCsv.isError ? "The CSV could not be imported." : null;
  const deleteError = deleteAccount.error instanceof ApiError ? deleteAccount.error.message : deleteAccount.isError ? "The account could not be deleted." : null;

  return (
    <section className="panel form-stack settings-form data-privacy-panel">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">Data & privacy</span>
          <h2>Your data, your copy</h2>
          <p>Export your Budget data, bring in CSV history, or permanently remove your account.</p>
        </div>
      </div>

      {downloadError && <div className="inline-alert" role="alert">{downloadError}</div>}
      <div className="privacy-downloads">
        <div>
          <strong>Portable exports</strong>
          <small>The JSON archive excludes passwords, session tokens, 2FA secrets, and Plaid access tokens.</small>
        </div>
        <div className="button-row">
          <button className="button secondary" type="button" onClick={() => void download("/privacy/export")}>Download all data</button>
          <button className="button secondary" type="button" onClick={() => void download("/privacy/transactions.csv")}>Transactions CSV</button>
        </div>
      </div>

      <form className="privacy-import form-stack" onSubmit={submitImport}>
        <div>
          <strong>Import transaction history</strong>
          <small>CSV imports go into manual accounts so they cannot collide with Plaid-managed history. Re-importing the same rows is safely skipped.</small>
        </div>
        {importError && <div className="inline-alert" role="alert">{importError}</div>}
        {importCsv.data && (
          <div className={`inline-alert${importCsv.data.errors.length ? "" : " success"}`} role="status">
            Imported {importCsv.data.imported}, skipped {importCsv.data.skipped_duplicates} duplicate{importCsv.data.skipped_duplicates === 1 ? "" : "s"}.
            {importCsv.data.errors.length ? ` ${importCsv.data.errors.length} row error${importCsv.data.errors.length === 1 ? "" : "s"}; first: row ${importCsv.data.errors[0].row} — ${importCsv.data.errors[0].message}` : ""}
          </div>
        )}
        <div className="form-grid two-columns">
          <label>Manual account
            <select value={accountId} onChange={(event) => setAccountId(event.target.value)} disabled={!manualAccounts.length}>
              <option value="">{manualAccounts.length ? "Choose an account" : "No manual accounts available"}</option>
              {manualAccounts.map((account) => <option value={account.id} key={account.id}>{account.display_name}</option>)}
            </select>
          </label>
          <label>CSV file
            <input type="file" accept=".csv,text/csv" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </label>
        </div>
        <div className="form-actions spread">
          <button className="button secondary" type="button" onClick={() => void download("/privacy/import-template.csv")}>Download template</button>
          <button className="button primary" type="submit" disabled={importCsv.isPending || !file || !accountId}>{importCsv.isPending ? "Importing…" : "Import CSV"}</button>
        </div>
      </form>

      <div className="privacy-danger-zone form-stack">
        <div>
          <strong>Delete Budget account</strong>
          <small>This permanently removes your local Budget data and disconnects your Plaid Items. This cannot be undone.</small>
        </div>
        {deleteError && <div className="inline-alert" role="alert">{deleteError}</div>}
        <div className="form-grid two-columns">
          <label>Type DELETE<input value={deleteConfirmation} onChange={(event) => setDeleteConfirmation(event.target.value)} autoComplete="off" /></label>
          <label>Current password <span className="optional">If your account has one</span><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" /></label>
        </div>
        <div className="form-actions end">
          <button className="button danger" type="button" disabled={deleteConfirmation !== "DELETE" || deleteAccount.isPending} onClick={() => {
            if (window.confirm("Permanently delete this Budget account and all of its local data?")) deleteAccount.mutate();
          }}>{deleteAccount.isPending ? "Deleting…" : "Delete my account"}</button>
        </div>
      </div>
    </section>
  );
}
