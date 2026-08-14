import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "../api/client";
import { queryKeys } from "../api/queries";
import type { OperationalJobStatus, OperationalStatus, OperationsStatus } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ErrorState, LoadingState } from "./States";

function bytes(value: number | null): string {
  if (value === null) return "Unavailable";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let amount = value / 1024;
  let unit = units[0];
  for (let index = 1; index < units.length && amount >= 1024; index += 1) {
    amount /= 1024;
    unit = units[index];
  }
  return `${amount.toFixed(amount >= 10 ? 1 : 2)} ${unit}`;
}

function time(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Not yet";
}

function statusLabel(status: OperationalStatus): string {
  if (status === "healthy") return "Healthy";
  if (status === "attention") return "Needs attention";
  if (status === "failed") return "Failed";
  if (status === "running") return "Running";
  return "Not applicable";
}

function pillClass(status: OperationalStatus): string {
  if (status === "healthy") return "status-pill success";
  if (status === "failed" || status === "attention") return "status-pill warning";
  return "status-pill";
}

function JobRow({ label, job }: { label: string; job: OperationalJobStatus }) {
  return (
    <div className="operations-row">
      <div>
        <strong>{label}</strong>
        <small>Last successful run: {time(job.last_success_at)}{job.age_hours !== null ? ` · ${job.age_hours}h ago` : ""}</small>
        {job.error_code && <small>Error code: {job.error_code}</small>}
      </div>
      <span className={pillClass(job.status)}>{statusLabel(job.status)}</span>
    </div>
  );
}

export function OperationsStatusCard() {
  const { user } = useAuth();
  const status = useQuery({
    queryKey: queryKeys.operationsStatus,
    queryFn: () => apiRequest<OperationsStatus>("/operations/status"),
    enabled: Boolean(user?.is_admin),
    refetchInterval: 60_000,
  });

  if (!user?.is_admin) return null;
  if (status.isPending) return <section className="panel operations-panel"><LoadingState label="Loading system health" /></section>;
  if (status.isError || !status.data) return <section className="panel operations-panel"><ErrorState title="System health unavailable" message="Budget could not load the reliability status." onRetry={() => void status.refetch()} /></section>;

  const data = status.data;
  return (
    <section className="settings-operations" aria-labelledby="operations-heading">
      <div className="settings-section-heading operations-heading">
        <div>
          <span className="eyebrow">Reliability & backups</span>
          <h2 id="operations-heading">System health</h2>
          <p>Admin-only status for Budget's database, backups, and scheduled workers.</p>
        </div>
        <span className={`status-pill ${data.overall === "healthy" ? "success" : "warning"}`}>{data.overall === "healthy" ? "All systems healthy" : "Needs attention"}</span>
      </div>

      {data.attention.length > 0 && <div className="inline-alert operations-alert" role="status">{data.attention.join(" ")}</div>}

      <div className="operations-grid">
        <article className="panel operations-card">
          <div className="security-card-heading"><div><span className="eyebrow">Database</span><h3>Database & schema</h3></div><span className={`status-pill ${data.migration.status === "healthy" ? "success" : "warning"}`}>{data.migration.status === "healthy" ? "Current" : "Migration needed"}</span></div>
          <div className="operations-row"><div><strong>Connection</strong><small>Application database query</small></div><span className="status-pill success">Healthy</span></div>
          <div className="operations-meta"><span>Schema</span><strong>{data.migration.current ?? "Unknown"}</strong><small>Application head: {data.migration.head}</small></div>
        </article>

        <article className="panel operations-card">
          <div className="security-card-heading"><div><span className="eyebrow">Protection</span><h3>Backup storage</h3></div><span className={pillClass(data.jobs.database_backup.status)}>{statusLabel(data.jobs.database_backup.status)}</span></div>
          <div className="operations-stat-grid">
            <div><small>Archives</small><strong>{data.backup_storage.archive_count}</strong></div>
            <div><small>Stored</small><strong>{bytes(data.backup_storage.archive_bytes)}</strong></div>
            <div><small>Free disk</small><strong>{bytes(data.backup_storage.free_bytes)}</strong></div>
          </div>
          <small className="muted-copy operations-path">{data.backup_storage.path}</small>
        </article>

        <article className="panel operations-card operations-jobs">
          <div className="security-card-heading"><div><span className="eyebrow">Scheduled work</span><h3>Worker history</h3></div><button className="button ghost" type="button" onClick={() => void status.refetch()}>Refresh</button></div>
          <JobRow label="Database backup" job={data.jobs.database_backup} />
          <JobRow label="Backup verification" job={data.jobs.backup_verify} />
          <JobRow label="Reporting snapshot" job={data.jobs.report_snapshot} />
          <JobRow label="Plaid sync" job={data.jobs.plaid_sync} />
        </article>
      </div>
    </section>
  );
}
