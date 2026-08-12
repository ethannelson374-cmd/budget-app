import { Icon } from "./Icon";

export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <div className="state-card" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}…</span>
    </div>
  );
}

export function PageLoading({ label = "Loading your budget" }: { label?: string }) {
  return (
    <main className="centered-page">
      <LoadingState label={label} />
    </main>
  );
}

export function ErrorState({
  title = "Something went wrong",
  message,
  requestId,
  onRetry,
}: {
  title?: string;
  message: string;
  requestId?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="state-card error-state" role="alert">
      <div>
        <h2>{title}</h2>
        <p>{message}</p>
        {requestId && <p className="request-id">Request ID: {requestId}</p>}
      </div>
      {onRetry && <button type="button" className="button secondary" onClick={onRetry}><Icon name="refresh" />Try again</button>}
    </div>
  );
}

export function EmptyState({ title, message, action }: { title: string; message: string; action?: React.ReactNode }) {
  return (
    <div className="state-card empty-state">
      <span className="empty-icon" aria-hidden="true"><Icon name="wallet" /></span>
      <div><h2>{title}</h2><p>{message}</p></div>
      {action}
    </div>
  );
}
