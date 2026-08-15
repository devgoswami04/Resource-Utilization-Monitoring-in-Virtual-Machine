import HealthBadge from "./HealthBadge";


const priorityTone = {
  low: "normal",
  medium: "warning",
  high: "critical",
  critical: "emergency",
};


const formatImpact = (recommendation) => {
  const chips = [];
  if (recommendation.impact?.cpu_points > 0) {
    chips.push(`${recommendation.impact.cpu_points.toFixed(1)} CPU pts`);
  }
  if (recommendation.impact?.memory_mb > 0) {
    chips.push(`${(recommendation.impact.memory_mb / 1024).toFixed(2)} GB RAM`);
  }
  if (recommendation.impact?.disk_mb > 0) {
    chips.push(`${(recommendation.impact.disk_mb / 1024).toFixed(2)} GB disk`);
  }
  if (recommendation.impact?.health_points > 0) {
    chips.push(`+${recommendation.impact.health_points.toFixed(1)} health`);
  }
  return chips;
};


export default function RecommendationBoard({ recommendations = [] }) {
  return (
    <article className="surface-card recommendation-panel">
      <div className="section-top">
        <div>
          <p className="preview-label">Suggestion playbook</p>
          <h3>Manual actions with real projected payoff</h3>
        </div>
        <span className="feed-count">{recommendations.length} live suggestions</span>
      </div>

      {recommendations.length ? (
        <div className="recommendation-list">
          {recommendations.map((recommendation, index) => (
            <section key={recommendation.id} className={`recommendation-card priority-${recommendation.priority}`}>
              <div className="recommendation-top">
                <div>
                  <span className="recommendation-order">{String(index + 1).padStart(2, "0")}</span>
                  <h4>{recommendation.title}</h4>
                </div>
                <HealthBadge
                  tone={priorityTone[recommendation.priority] ?? "warning"}
                  label={recommendation.priority}
                  compact
                />
              </div>

              <p className="recommendation-summary">{recommendation.summary}</p>

              <div className="recommendation-meta">
                <span>{recommendation.lane}</span>
                <span>{recommendation.effort}</span>
                <span>{Math.round((recommendation.confidence ?? 0) * 100)}% confidence</span>
              </div>

              <div className="impact-chip-row">
                {formatImpact(recommendation).map((chip) => (
                  <span key={chip} className="impact-chip">
                    {chip}
                  </span>
                ))}
              </div>

              <div className="recommendation-columns">
                <div>
                  <p className="preview-label">Evidence</p>
                  <ul className="detail-list">
                    {recommendation.evidence.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>

                <div>
                  <p className="preview-label">Manual steps</p>
                  <ul className="detail-list">
                    {recommendation.manual_steps.map((step) => (
                      <li key={step}>{step}</li>
                    ))}
                  </ul>
                </div>
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className="empty-panel">Recommendations will appear here as soon as live telemetry identifies reclaim opportunities.</div>
      )}
    </article>
  );
}
