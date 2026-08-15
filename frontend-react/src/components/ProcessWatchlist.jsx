import HealthBadge from "./HealthBadge";


const impactTone = {
  low: "normal",
  medium: "warning",
  high: "critical",
};


export default function ProcessWatchlist({ watchlist = [] }) {
  return (
    <article className="surface-card watchlist-panel">
      <div className="section-top">
        <div>
          <p className="preview-label">Live watchlist</p>
          <h3>Apps the advisor is tracking right now</h3>
        </div>
        <span className="feed-count">{watchlist.length} processes</span>
      </div>

      {watchlist.length ? (
        <div className="watchlist-table">
          {watchlist.map((process) => (
            <div key={`${process.pid}-${process.name}`} className="watchlist-row">
              <div className="watchlist-main">
                <div className="watchlist-heading">
                  <strong>{process.name}</strong>
                  <span>{process.category}</span>
                </div>
                <p>{process.operator_hint}</p>
              </div>

              <div className="watchlist-metrics">
                <div>
                  <span>CPU</span>
                  <strong>{process.cpu_percent.toFixed(1)}%</strong>
                </div>
                <div>
                  <span>Memory</span>
                  <strong>{(process.memory_mb / 1024).toFixed(2)} GB</strong>
                </div>
                <div>
                  <span>Runtime</span>
                  <strong>{process.runtime_minutes.toFixed(0)} min</strong>
                </div>
              </div>

              <div className="watchlist-badges">
                <HealthBadge
                  tone={impactTone[process.business_impact] ?? "warning"}
                  label={`${process.business_impact} impact`}
                  compact
                />
                <span className="watchlist-style">{process.action_style}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="empty-panel">The watchlist will populate as soon as the agent reports top process telemetry.</div>
      )}
    </article>
  );
}
