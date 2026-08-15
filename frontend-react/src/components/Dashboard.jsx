import { startTransition, useCallback, useEffect, useMemo, useRef, useState } from "react";
import ChartCard from "./ChartCard";
import HealthBadge from "./HealthBadge";
import ImpactStudio from "./ImpactStudio";
import IncidentTimeline from "./IncidentTimeline";
import PredictionPanel from "./PredictionPanel";
import ProcessWatchlist from "./ProcessWatchlist";
import RecommendationBoard from "./RecommendationBoard";
import StatCard from "./StatCard";


const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";


const formatTimestamp = (value) => {
  if (!value) {
    return "Awaiting telemetry";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    month: "short",
    day: "numeric",
  });
};


export default function Dashboard({ theme, onToggleTheme, onBack }) {
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const isFetchingRef = useRef(false);

  const fetchDashboard = useCallback(async (showLoader = false) => {
    if (isFetchingRef.current) {
      return;
    }

    isFetchingRef.current = true;
    if (showLoader) {
      setRefreshing(true);
    }

    try {
      const response = await fetch(`${API_BASE}/dashboard?t=${Date.now()}`, {
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(`Dashboard request failed with status ${response.status}`);
      }

      const payload = await response.json();
      startTransition(() => {
        setDashboard(payload);
        setLoading(false);
        setError("");
      });
    } catch (requestError) {
      setError(requestError.message || "Unable to reach backend");
      setLoading(false);
    } finally {
      isFetchingRef.current = false;
      if (showLoader) {
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timerId = null;

    const scheduleNext = () => {
      if (cancelled) {
        return;
      }
      timerId = window.setTimeout(async () => {
        await fetchDashboard();
        scheduleNext();
      }, 8000);
    };

    fetchDashboard().finally(() => {
      scheduleNext();
    });

    return () => {
      cancelled = true;
      if (timerId !== null) {
        window.clearTimeout(timerId);
      }
    };
  }, [fetchDashboard]);

  const summary = dashboard?.summary ?? null;
  const current = summary?.current_metrics ?? null;
  const prediction = summary?.prediction ?? null;
  const advisor = dashboard?.advisor ?? null;
  const metrics = dashboard?.metrics ?? [];
  const incidents = dashboard?.incidents ?? [];

  const severityTone = prediction?.severity ?? current?.severity_level ?? "normal";
  const projectedMemoryGb = (advisor?.what_if?.estimated_gain?.memory_mb ?? 0) / 1024;
  const projectedDiskGb = (advisor?.what_if?.estimated_gain?.disk_mb ?? 0) / 1024;

  const cards = useMemo(
    () => [
      {
        title: "CPU usage",
        value: current?.cpu ?? "--",
        tone: severityTone,
        accent: "var(--accent-cyan)",
        description: "Live processor saturation coming from the telemetry agent.",
        icon: "cpu",
      },
      {
        title: "Memory pressure",
        value: current?.memory ?? "--",
        tone: current?.memory >= 80 ? "critical" : current?.memory >= 65 ? "warning" : "normal",
        accent: "var(--accent-amber)",
        description: "Current RAM pressure across the local machine.",
        icon: "memory",
      },
      {
        title: "Disk utilization",
        value: current?.disk ?? "--",
        tone: current?.disk >= 88 ? "critical" : current?.disk >= 72 ? "warning" : "normal",
        accent: "var(--accent-rose)",
        description: "Total storage occupancy on the monitored drive.",
        icon: "disk",
      },
      {
        title: "Health score",
        value: current?.health_score ?? "--",
        unit: typeof current?.health_score === "number" ? " / 100" : "",
        tone: severityTone,
        accent: "var(--accent-emerald)",
        description: "Composite health score from the prediction stack.",
        icon: "health",
      },
      {
        title: "Predicted CPU",
        value: prediction?.predicted_cpu ?? "--",
        tone: severityTone,
        accent: "var(--accent-sky)",
        description: "Forecasted CPU for the next interval.",
        icon: "forecast",
      },
      {
        title: "Reclaimable RAM",
        value: projectedMemoryGb,
        unit: typeof projectedMemoryGb === "number" ? " GB" : "",
        tone: projectedMemoryGb >= 1 ? "critical" : projectedMemoryGb >= 0.35 ? "warning" : "normal",
        accent: "var(--accent-gold)",
        description: "Projected memory that the top suggestions could free.",
        icon: "advisor",
      },
    ],
    [current, prediction, projectedMemoryGb, severityTone],
  );

  return (
    <main className="dashboard-page">
      <header className="console-topbar">
        <div>
          <p className="landing-kicker">Aegis Resource Advisor</p>
          <h1>Mission-aware optimization deck</h1>
        </div>

        <div className="console-topbar-actions">
          <HealthBadge tone={summary?.live_connection ?? "waiting"} label={summary?.live_connection ?? "waiting"} />
          <button className="ghost-button" onClick={() => fetchDashboard(true)} type="button">
            {refreshing ? "Refreshing..." : "Refresh data"}
          </button>
          <button className="ghost-button" onClick={onBack} type="button">
            Overview
          </button>
          <button className="ghost-button" onClick={onToggleTheme} type="button">
            {theme === "dark" ? "Light mode" : "Dark mode"}
          </button>
        </div>
      </header>

      <section className="command-stage">
        <article className="surface-card mission-brief">
          <div className="section-top">
            <div>
              <p className="preview-label">Operator briefing</p>
              <h2>{summary?.system_health ?? "Collecting"}</h2>
            </div>
            <HealthBadge tone={severityTone} label={prediction?.severity ?? "normal"} />
          </div>

          <p className="mission-copy">
            {current?.alert_message ?? prediction?.alert_message ?? "The platform is waiting for live telemetry samples."}
          </p>

          <div className="mission-pill-row">
            <span className="telemetry-pill">Host {current?.hostname ?? "--"}</span>
            <span className="telemetry-pill">Environment {current?.environment ?? "--"}</span>
            <span className="telemetry-pill">{advisor?.recommendations?.length ?? 0} active suggestions</span>
          </div>

          <div className="mission-grid">
            <div className="mission-stat">
              <span>Last update</span>
              <strong>{formatTimestamp(summary?.generated_at)}</strong>
            </div>
            <div className="mission-stat">
              <span>Prediction confidence</span>
              <strong>{prediction?.confidence != null ? `${Math.round(prediction.confidence * 100)}%` : "--"}</strong>
            </div>
            <div className="mission-stat">
              <span>Potential disk reclaim</span>
              <strong>{projectedDiskGb > 0 ? `${projectedDiskGb.toFixed(2)} GB` : "--"}</strong>
            </div>
            <div className="mission-stat">
              <span>Unique feature</span>
              <strong>{advisor?.differentiator_title ?? "Intent lens"}</strong>
            </div>
          </div>

          <div className="feature-banner">
            <p className="preview-label">{advisor?.differentiator_title ?? "Intent-aware advisor"}</p>
            <p>{advisor?.differentiator_body ?? "The advisor will explain what makes this platform different once telemetry arrives."}</p>
          </div>
        </article>

        <ImpactStudio scenario={advisor?.what_if} />
      </section>

      {error ? <div className="banner-error">{error}</div> : null}
      {loading ? <div className="loading-banner">Connecting to backend and building the advisory dashboard...</div> : null}

      <section className="metric-grid">
        {cards.map((card) => (
          <StatCard key={card.title} {...card} />
        ))}
      </section>

      <section className="chart-grid">
        <ChartCard
          title="CPU"
          subtitle="Real-time CPU versus prediction"
          items={metrics}
          dataKey="cpu"
          secondaryKey="predicted_cpu"
          secondaryLabel="Predicted CPU"
          secondaryAccent="rgba(255, 199, 102, 0.95)"
          accent="var(--accent-cyan)"
          fill="rgba(68, 209, 255, 0.16)"
          theme={theme}
        />
        <ChartCard
          title="Memory"
          subtitle="Live memory pressure"
          items={metrics}
          dataKey="memory"
          accent="var(--accent-amber)"
          fill="rgba(255, 181, 98, 0.18)"
          theme={theme}
        />
        <ChartCard
          title="Disk"
          subtitle="Disk occupancy trend"
          items={metrics}
          dataKey="disk"
          accent="var(--accent-rose)"
          fill="rgba(255, 116, 147, 0.18)"
          theme={theme}
        />
        <ChartCard
          title="Health"
          subtitle="Composite health score"
          items={metrics}
          dataKey="health_score"
          accent="var(--accent-emerald)"
          fill="rgba(62, 221, 156, 0.18)"
          theme={theme}
          formatter={(value) => `${value.toFixed(1)} pts`}
        />
      </section>

      <section className="advisor-layout">
        <PredictionPanel current={current} prediction={prediction} advisor={advisor} />
        <RecommendationBoard recommendations={advisor?.recommendations ?? []} />
      </section>

      <section className="intel-layout">
        <ProcessWatchlist watchlist={advisor?.watchlist ?? []} />
        <IncidentTimeline incidents={incidents.slice(0, 6)} totalCount={incidents.length} />
      </section>
    </main>
  );
}
