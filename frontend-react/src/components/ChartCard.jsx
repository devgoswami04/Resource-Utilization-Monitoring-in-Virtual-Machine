import { useMemo } from "react";
import { Line } from "react-chartjs-2";
import "chart.js/auto";


const formatTime = (value) => {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value?.slice?.(-8) ?? "--";
  }
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};


export default function ChartCard({
  title,
  subtitle,
  items,
  dataKey,
  secondaryKey,
  secondaryLabel,
  secondaryAccent,
  accent,
  fill,
  theme,
  maxValue = 100,
  formatter = (value) => `${value.toFixed(1)}%`,
}) {
  const chartData = useMemo(
    () => {
      const datasets = [
        {
          label: title,
          data: items.map((item) => item[dataKey] ?? 0),
          borderColor: accent,
          backgroundColor: fill,
          borderWidth: 2.5,
          fill: true,
          tension: 0.35,
          pointRadius: 0,
          pointHoverRadius: 4,
        },
      ];

      if (secondaryKey) {
        datasets.push({
          label: secondaryLabel ?? secondaryKey,
          data: items.map((item) => item[secondaryKey] ?? null),
          borderColor: secondaryAccent ?? accent,
          borderDash: [8, 6],
          borderWidth: 2,
          fill: false,
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 3,
        });
      }

      return {
        labels: items.map((item) => formatTime(item.timestamp)),
        datasets,
      };
    },
    [accent, dataKey, fill, items, secondaryAccent, secondaryKey, secondaryLabel, title],
  );

  const options = useMemo(() => {
    const dark = theme === "dark";
    return {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: dark ? "rgba(12, 18, 32, 0.96)" : "rgba(255, 255, 255, 0.96)",
          titleColor: dark ? "#f5f7ff" : "#0f172a",
          bodyColor: dark ? "#e0ecff" : "#0f172a",
          borderColor: dark ? "rgba(128, 156, 255, 0.22)" : "rgba(15, 23, 42, 0.12)",
          borderWidth: 1,
          callbacks: { label: (context) => formatter(context.parsed.y) },
        },
      },
      scales: {
        x: {
          grid: { color: dark ? "rgba(131, 146, 203, 0.08)" : "rgba(46, 77, 128, 0.08)" },
          ticks: { color: dark ? "#8ea3cc" : "#5c6f90", maxTicksLimit: 6 },
        },
        y: {
          grid: { color: dark ? "rgba(131, 146, 203, 0.08)" : "rgba(46, 77, 128, 0.08)" },
          ticks: { color: dark ? "#8ea3cc" : "#5c6f90" },
          min: 0,
          max: maxValue,
        },
      },
    };
  }, [formatter, maxValue, theme]);

  const latestValue = items.length ? items[items.length - 1][dataKey] : null;

  return (
    <article className="surface-card chart-card">
      <div className="chart-card-top">
        <div>
          <p className="preview-label">{title}</p>
          <h3>{subtitle}</h3>
        </div>
        <strong style={{ color: accent }}>{latestValue != null ? formatter(latestValue) : "--"}</strong>
      </div>
      <div className="chart-shell">
        {items.length ? <Line data={chartData} options={options} /> : <div className="chart-empty">Awaiting telemetry</div>}
      </div>
    </article>
  );
}
