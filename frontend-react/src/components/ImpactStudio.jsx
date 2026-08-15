const resources = [
  { key: "cpu", label: "CPU", unit: "%" },
  { key: "memory", label: "Memory", unit: "%" },
  { key: "disk", label: "Disk", unit: "%" },
  { key: "health_score", label: "Health", unit: "" },
];


const formatValue = (value, unit) => {
  if (value == null) {
    return "--";
  }
  return `${value.toFixed(1)}${unit}`;
};


export default function ImpactStudio({ scenario }) {
  const actions = scenario?.actions ?? [];

  return (
    <article className="surface-card impact-studio">
      <div className="section-top">
        <div>
          <p className="preview-label">Unique element</p>
          <h3>{scenario?.title ?? "Impact simulation"}</h3>
        </div>
        <span className="feed-count">{Math.round((scenario?.confidence ?? 0) * 100)}% confidence</span>
      </div>

      <p className="impact-summary">
        {scenario?.summary ??
          "The simulator estimates how much the system could recover if the top manual suggestions are applied."}
      </p>

      <div className="impact-grid">
        {resources.map((resource) => {
          const before = scenario?.before?.[resource.key] ?? null;
          const after = scenario?.after?.[resource.key] ?? null;
          const delta = before != null && after != null ? before - after : null;

          return (
            <div key={resource.key} className="impact-metric">
              <div className="impact-metric-top">
                <span>{resource.label}</span>
                <strong>{delta != null ? `${delta > 0 ? "-" : "+"}${Math.abs(delta).toFixed(1)}${resource.unit}` : "--"}</strong>
              </div>
              <div className="impact-bars">
                <div className="impact-bar">
                  <span className="impact-bar-label">Before</span>
                  <div className="impact-bar-track">
                    <div className="impact-bar-fill before" style={{ width: `${Math.min(before ?? 0, 100)}%` }} />
                  </div>
                  <span className="impact-bar-value">{formatValue(before, resource.unit)}</span>
                </div>
                <div className="impact-bar">
                  <span className="impact-bar-label">After</span>
                  <div className="impact-bar-track">
                    <div className="impact-bar-fill after" style={{ width: `${Math.min(after ?? 0, 100)}%` }} />
                  </div>
                  <span className="impact-bar-value">{formatValue(after, resource.unit)}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="impact-actions">
        <p className="preview-label">Scenario actions</p>
        <div className="impact-action-row">
          {actions.map((action) => (
            <span key={action.recommendation_id} className="impact-action-chip">
              {action.title}
            </span>
          ))}
        </div>
      </div>

      <p className="impact-footnote">{scenario?.differentiator}</p>
    </article>
  );
}
