import HealthBadge from "./HealthBadge";


const icons = {
  cpu: "CPU",
  memory: "MEM",
  disk: "DSK",
  health: "HLT",
  forecast: "AIP",
  anomaly: "ALT",
  advisor: "ADV",
};


export default function StatCard({
  title,
  value,
  unit = "%",
  tone = "normal",
  accent = "var(--accent-cyan)",
  description,
  icon = "cpu",
}) {
  const displayValue = typeof value === "number" ? value.toFixed(1) : value;

  return (
    <article className={`surface-card metric-card tone-card-${tone}`} style={{ "--card-accent": accent }}>
      <div className="metric-card-top">
        <div>
          <p className="preview-label">{title}</p>
          <h3 key={displayValue} className="metric-value">
            {displayValue}
            {typeof value === "number" ? <span>{unit}</span> : null}
          </h3>
        </div>
        <div className="metric-card-side">
          <HealthBadge tone={tone} compact />
          <span className="metric-icon">{icons[icon] ?? "SYS"}</span>
        </div>
      </div>
      <p className="metric-description">{description}</p>
      <div className="metric-progress">
        <span style={{ width: typeof value === "number" ? `${Math.min(value, 100)}%` : "64%" }} />
      </div>
    </article>
  );
}
