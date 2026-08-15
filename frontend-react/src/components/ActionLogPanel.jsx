import HealthBadge from "./HealthBadge";


const formatTimestamp = (value) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value ?? "--";
  }
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
};


export default function ActionLogPanel({ actions, totalCount = 0 }) {
  return (
    <article className="surface-card feed-card">
      <div className="feed-header">
        <div>
          <p className="preview-label">Action history</p>
          <h3>Remediation execution log</h3>
        </div>
        <span className="feed-count">
          Showing {actions.length}
          {totalCount > actions.length ? ` of ${totalCount}` : ""}
        </span>
      </div>

      {actions.length ? (
        <div className="feed-list">
          {actions.map((action) => (
            <div key={action.id} className="feed-row">
              <div className="feed-row-top">
                <HealthBadge tone={action.severity} compact label={action.status} />
                <span>{formatTimestamp(action.created_at)}</span>
              </div>
              <strong>{action.action_type.replaceAll("_", " ")}</strong>
              <p>{action.result_summary ?? action.notes ?? "Action logged."}</p>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-panel">No remediation action has been triggered yet. Manual and autonomous runs will appear here.</div>
      )}
    </article>
  );
}
