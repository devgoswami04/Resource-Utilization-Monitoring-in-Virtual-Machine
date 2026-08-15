import HealthBadge from "./HealthBadge";


export default function PredictionPanel({ current, prediction, advisor }) {
  const confidence = typeof prediction?.confidence === "number" ? Math.round(prediction.confidence * 100) : 0;

  return (
    <article className="surface-card prediction-panel">
      <div className="prediction-hero">
        <div>
          <p className="preview-label">Signal center</p>
          <h2>{prediction?.alert_message ?? "Awaiting telemetry insights"}</h2>
        </div>
        <HealthBadge tone={prediction?.severity ?? "normal"} />
      </div>

      <div className="prediction-grid">
        <div className="prediction-score">
          <span>Predicted CPU</span>
          <strong>{prediction?.predicted_cpu != null ? `${prediction.predicted_cpu.toFixed(1)}%` : "--"}</strong>
          <small>{prediction?.anomaly ? "Anomaly detected" : "Pattern within expected baseline"}</small>
        </div>

        <div className="prediction-meta">
          <div>
            <span className="preview-label">Confidence</span>
            <strong>{confidence}%</strong>
          </div>
          <div>
            <span className="preview-label">Advisor posture</span>
            <strong>{advisor?.differentiator_title ?? "Intent-aware review"}</strong>
          </div>
        </div>
      </div>

      <div className="signal-list">
        <div className="signal-chip">
          <span>CPU trend</span>
          <strong>{prediction?.trend?.cpu_direction ?? "stable"}</strong>
        </div>
        <div className="signal-chip">
          <span>Memory trend</span>
          <strong>{prediction?.trend?.memory_direction ?? "stable"}</strong>
        </div>
        <div className="signal-chip">
          <span>Disk trend</span>
          <strong>{prediction?.trend?.disk_direction ?? "stable"}</strong>
        </div>
        <div className="signal-chip">
          <span>Current health</span>
          <strong>{current?.health_score != null ? `${current.health_score.toFixed(1)} / 100` : "--"}</strong>
        </div>
      </div>

      <div className="advisor-brief">
        <p className="preview-label">Advisor brief</p>
        <p>{advisor?.subheadline ?? "The advisor will explain the safest manual response once telemetry stabilizes."}</p>
      </div>

      <div className="explanation-block">
        <p className="preview-label">Why the system made this call</p>
        <p>{prediction?.explanation ?? current?.decision_explanation ?? "The console will explain its decision once enough telemetry arrives."}</p>
      </div>
    </article>
  );
}
