import { Link } from "react-router-dom";
import type { InsightItem } from "../api/types";

const labels = {
  critical: "Critical",
  important: "Important",
  opportunity: "Opportunity",
  info: "FYI",
} as const;

export function InsightCard({
  insight,
  compact = false,
  busy = false,
  onDismiss,
  onRestore,
}: {
  insight: InsightItem;
  compact?: boolean;
  busy?: boolean;
  onDismiss?: (insight: InsightItem) => void;
  onRestore?: (insight: InsightItem) => void;
}) {
  return (
    <article className={`insight-card priority-${insight.priority}`}>
      <div className="insight-card-heading">
        <div>
          <span className={`insight-priority ${insight.priority}`}>{labels[insight.priority]}</span>
          <span className="insight-category">{insight.category.replaceAll("_", " ")}</span>
        </div>
        <span className="insight-score">{insight.score}</span>
      </div>
      <h3>{insight.title}</h3>
      <p>{insight.summary}</p>
      {!compact && insight.evidence.length > 0 && (
        <dl className="insight-evidence">
          {insight.evidence.map((item) => (
            <div key={`${item.label}-${item.value}`}>
              <dt>{item.label}</dt>
              <dd>{item.value}{item.detail && <small>{item.detail}</small>}</dd>
            </div>
          ))}
        </dl>
      )}
      {insight.recommendation && !compact && (
        <div className="insight-recommendation">
          <strong>Recommended next step</strong>
          <p>{insight.recommendation}</p>
        </div>
      )}
      <div className="insight-actions">
        {insight.action_route && <Link className="text-link" to={insight.action_route}>Review details <span aria-hidden="true">→</span></Link>}
        {insight.status === "active" && onDismiss && <button className="button ghost" type="button" disabled={busy} onClick={() => onDismiss(insight)}>Dismiss</button>}
        {insight.status === "dismissed" && onRestore && <button className="button ghost" type="button" disabled={busy} onClick={() => onRestore(insight)}>Restore</button>}
      </div>
    </article>
  );
}
