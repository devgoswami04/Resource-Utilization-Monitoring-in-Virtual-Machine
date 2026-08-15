const toneLabels = {
  normal: "Normal",
  warning: "Warning",
  critical: "Critical",
  emergency: "Emergency",
  connected: "Connected",
  stale: "Stale",
  waiting: "Waiting",
  healthy: "Healthy",
};


export default function HealthBadge({ tone = "normal", label, compact = false }) {
  const resolvedLabel = label ?? toneLabels[tone] ?? tone;
  return (
    <span className={`health-badge tone-${tone}${compact ? " compact" : ""}`}>
      <span className="health-badge-dot" />
      {resolvedLabel}
    </span>
  );
}
