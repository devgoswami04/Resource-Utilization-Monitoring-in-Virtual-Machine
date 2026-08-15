import { useEffect, useState } from "react";


const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";


const pipeline = [
  "Monitoring Agent",
  "Telemetry Ingestion",
  "Prediction Engine",
  "Intent Lens",
  "Impact Simulator",
  "Manual Playbooks",
];


// Shown before live telemetry arrives, or if the backend is unreachable, so the
// hero still reads well in a cold demo.
const SAMPLE_PREVIEW = {
  live: false,
  headline: "Under pressure, but recoverable",
  health: "81",
  cpu: "71.4%",
  memory: "63.8%",
  disk: "79.2%",
  recovery: "+12.3 pts",
  recommendation:
    "Close Spotify, trim unused Chrome tabs, and clear temporary artifacts to reclaim CPU, RAM, and disk without touching protected workloads.",
};


const asPercent = (value) =>
  typeof value === "number" && Number.isFinite(value) ? `${value.toFixed(1)}%` : null;


const buildPreview = (dashboard) => {
  const summary = dashboard?.summary ?? {};
  const current = summary.current_metrics ?? {};
  const advisor = dashboard?.advisor ?? {};
  const whatIf = advisor.what_if ?? {};
  const before = whatIf.before ?? {};
  const gain = whatIf.estimated_gain ?? {};

  const health = current.health_score ?? before.health_score;
  const recovery = gain.health_points;
  const recommendation =
    whatIf.summary ?? advisor.recommendations?.[0]?.summary ?? SAMPLE_PREVIEW.recommendation;

  return {
    live: true,
    headline: summary.system_health ?? advisor.headline ?? SAMPLE_PREVIEW.headline,
    health: typeof health === "number" ? Math.round(health).toString() : SAMPLE_PREVIEW.health,
    cpu: asPercent(current.cpu ?? before.cpu) ?? SAMPLE_PREVIEW.cpu,
    memory: asPercent(current.memory ?? before.memory) ?? SAMPLE_PREVIEW.memory,
    disk: asPercent(current.disk ?? before.disk) ?? SAMPLE_PREVIEW.disk,
    recovery:
      typeof recovery === "number" ? `+${recovery.toFixed(1)} pts` : SAMPLE_PREVIEW.recovery,
    recommendation,
  };
};


const highlights = [
  {
    title: "Intent-aware suggestions",
    body: "Rank the best manual actions by real app behavior, business importance, and estimated resource recovery.",
  },
  {
    title: "What-if recovery studio",
    body: "Show a live before-versus-after projection so operators can demonstrate measurable payoff without unsafe automation.",
  },
  {
    title: "Cloud-grade presentation",
    body: "Present telemetry, predictions, live watchlists, and guided playbooks in a console designed to impress in demos and reviews.",
  },
];


export default function LandingPage({ onEnter }) {
  const [preview, setPreview] = useState(SAMPLE_PREVIEW);

  useEffect(() => {
    const controller = new AbortController();

    const loadPreview = async () => {
      try {
        const response = await fetch(`${API_BASE}/dashboard?t=${Date.now()}`, {
          cache: "no-store",
          signal: controller.signal,
        });
        if (!response.ok) {
          return;
        }
        const payload = await response.json();
        setPreview(buildPreview(payload));
      } catch {
        // Keep the sample preview when the backend is unreachable.
      }
    };

    loadPreview();
    const timerId = window.setInterval(loadPreview, 8000);
    return () => {
      controller.abort();
      window.clearInterval(timerId);
    };
  }, []);

  return (
    <main className="landing-page">
      <div className="landing-orb landing-orb-one" />
      <div className="landing-orb landing-orb-two" />
      <section className="landing-hero">
        <div className="landing-copy">
          <div className="eyebrow-pill">
            <span className="pulse-dot" />
            Real-time resource intelligence for operator-led optimization
          </div>
          <p className="landing-kicker">Aegis Resource Advisor</p>
          <h1>
            Watch the system.
            <br />
            Explain the pressure.
            <br />
            Simulate the recovery.
          </h1>
          <p className="landing-summary">
            A polished control plane for real-time telemetry, ML-backed forecasting, and intent-aware
            optimization suggestions. Unlike generic dashboards, it understands which apps are optional,
            which are protected, and what manual action gives the best return.
          </p>
          <div className="landing-actions">
            <button className="primary-button" onClick={onEnter}>
              Launch live console
            </button>
            <div className="landing-proof">
              <strong>Unique feature</strong>
              <span>Workload intent lens + what-if recovery simulator</span>
            </div>
          </div>
        </div>

        <div className="hero-preview surface-card">
          <div className="preview-topline">
            <span>Control plane preview</span>
            <span>{preview.live ? "Live telemetry" : "Sample preview"}</span>
          </div>

          <div className="preview-health">
            <div>
              <p className="preview-label">Global health</p>
              <h2>{preview.headline}</h2>
            </div>
            <div className="preview-score">
              <strong>{preview.health}</strong>
              <span>Health score</span>
            </div>
          </div>

          <div className="preview-grid">
            <div className="preview-metric">
              <span>CPU</span>
              <strong>{preview.cpu}</strong>
            </div>
            <div className="preview-metric">
              <span>Memory</span>
              <strong>{preview.memory}</strong>
            </div>
            <div className="preview-metric">
              <span>Disk</span>
              <strong>{preview.disk}</strong>
            </div>
            <div className="preview-metric">
              <span>Projected recovery</span>
              <strong>{preview.recovery}</strong>
            </div>
          </div>

          <div className="preview-section">
            <p className="preview-label">Autonomous pipeline</p>
            <div className="pipeline-list">
              {pipeline.map((step) => (
                <div key={step} className="pipeline-chip">
                  {step}
                </div>
              ))}
            </div>
          </div>

          <div className="preview-section">
            <p className="preview-label">Recommended response</p>
            <div className="preview-banner">{preview.recommendation}</div>
          </div>
        </div>
      </section>

      <section className="landing-highlights">
        {highlights.map((highlight) => (
          <article key={highlight.title} className="surface-card feature-card">
            <p className="preview-label">{highlight.title}</p>
            <p>{highlight.body}</p>
          </article>
        ))}
      </section>
    </main>
  );
}
