# Aegis Resource Advisor

Real-time resource monitoring, ML-backed forecasting, and an intent-aware
optimization advisor. The backend samples the host machine, scores its health,
predicts short-term CPU pressure, and ranks safe manual actions an operator can
take. The React console visualises all of it and lets you simulate the impact of
a recovery plan before doing anything.

## Architecture

- **backend/** — FastAPI service (SQLite storage). Ingests telemetry, runs the
  predictor/decision engine, builds the advisor, and exposes the REST API. A
  built-in sampler (`backend/sampler.py`) reads the local machine every few
  seconds so the dashboard is live without a separate agent.
- **agent/** — Optional standalone telemetry agent (`agent/monitor.py`) that can
  push metrics to the API from another machine.
- **frontend-react/** — Vite + React dashboard and landing console.

## Requirements

- Python 3.11+
- Node.js 18+

## Setup

### Backend

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

The API is then available at `http://127.0.0.1:8000` (interactive docs at `/docs`).

### Frontend

```bash
cd frontend-react
npm install
npm run dev
```

Open `http://localhost:5173`.

## Configuration

Copy `.env.example` to `.env` at the repo root to override defaults. Notable
settings:

- `ENABLE_LOCAL_SAMPLER` — set `false` if you'd rather feed metrics only from the
  standalone agent instead of sampling the host that runs the API.
- `SAMPLER_INTERVAL_SECONDS` — how often the built-in sampler records a sample.
- `ALLOW_LIVE_REMEDIATION` — kept `false` by default; remediation stays in
  simulation mode unless explicitly enabled.

## API overview

| Method | Path         | Purpose                                      |
|--------|--------------|----------------------------------------------|
| GET    | `/health`    | Service and database status                  |
| GET    | `/summary`   | Latest metrics, prediction, and health label |
| GET    | `/predict`   | Current forecast and recommendation          |
| GET    | `/metrics`   | Recent metric history                        |
| POST   | `/metrics`   | Ingest a telemetry sample                    |
| GET    | `/actions`   | Remediation action history                   |
| POST   | `/remediate` | Run a remediation action (simulated by default) |
| GET    | `/dashboard` | Aggregated payload used by the frontend      |

## Notes

The local SQLite database and log file are machine-specific and are not tracked
in version control.
