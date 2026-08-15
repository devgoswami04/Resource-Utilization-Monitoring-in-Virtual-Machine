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


export default function IncidentTimeline({ incidents, totalCount = 0 }) {
  return (
    <article className="surface-card feed-card">
      <div className="feed-header">
        <div>
          <p className="preview-label">Incident timeline</p>
          <h3>Alerts and anomaly trail</h3>
        </div>
        <span className="feed-count">
          Showing {incidents.length}
          {totalCount > incidents.length ? ` of ${totalCount}` : ""}
        </span>
      </div>

      {incidents.length ? (
        <div className="feed-list">
          {incidents.map((incident) => (
            <div key={incident.id} className="feed-row">
              <div className="feed-row-top">
                <HealthBadge tone={incident.severity} compact />
                <span>{formatTimestamp(incident.created_at)}</span>
              </div>
              <strong>{incident.title}</strong>
              <p>{incident.message}</p>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-panel">No incidents are active. The timeline will populate when the platform detects pressure or anomalies.</div>
      )}
    </article>
  );
}
