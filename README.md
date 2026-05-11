# soiling_analysis

Standalone soiling-analysis package and local web interface for Shambhavi Green Energy.

This repo contains:

- `soiling_analysis/`: reusable Hampel filtering, cleaning-event detection, data quality, DB repository, and per-segment soiling-rate code.
- `index.html` / `styles.css`: browser interface for selecting parameters and rendering outputs.
- `soiling_analysis/web_server.py`: local background web server that runs the Python analysis.
- `scripts/alpha_sweep.py`: read-only IQR alpha sweep against plant-wide PR and rainfall.
- `tests/`: unit tests for the core algorithm pieces.
- `docs/`: implementation notes copied from the original working context.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
cp .env.example .env
```

Edit `.env` with the TigerData credentials. The real `.env` is intentionally ignored by git.

## Verify

```bash
python -m pytest
```

## Run the Web Interface

```bash
python -m soiling_analysis.web_server
```

Open `http://127.0.0.1:8765`, choose the plant, inverter, string port, date window, and exposed algorithm parameters, then run the analysis. The browser receives only results; TigerData credentials stay in the local Python server process.

## Run the Plant Pipeline

```bash
python -m soiling_analysis.run \
  --plant b0000000-0000-0000-0000-000000000002 \
  --start-date 2026-02-15 \
  --end-date 2026-05-05
```

This writes detected cleaning events and daily string soiling outputs back to the configured database.

## Run the Alpha Sweep

```bash
python scripts/alpha_sweep.py
```

The alpha sweep is read-only and scores cleaning-event detections against rainfall-proxy matches.
