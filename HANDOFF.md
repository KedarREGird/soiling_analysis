# Handoff: Soiling Analysis Web Interface

## Current State

- Local repo: `/Users/kedar/Desktop/Soiling Context & Code/soiling_analysis`
- GitHub repo: `https://github.com/KedarREGird/soiling_analysis`
- Current published branch: `main`
- Current commit: `2bdb1b1 Initial web app without notebook`
- GitHub Pages status: built
- GitHub Pages source: `main` branch, repository root
- Custom domain configured in GitHub Pages: `sa.kedardeshmukh.com`

The public repo has been rebuilt from a clean root commit so the notebook is not present in the published branch history.

## What This App Does

The project is now a browser-based interface for running the Shambhavi single-string soiling analysis.

The UI lets the user select:

- Plant UUID
- Inverter name
- String port
- Start and end date
- IQR alpha
- Rainfall threshold
- Advanced Hampel, cleaning-event, segment, and Prophet parameters

The Python server runs the analysis in the background and returns:

- Corrected PR series
- Hampel-filtered PR series
- Rainfall overlay
- Detected/classified cleaning events
- Per-segment Prophet trend lines
- Per-segment soiling rates
- Length-weighted overall soiling rate

## Important Architecture Note

GitHub Pages can only host static files. It cannot run the database-backed Python analysis or store private TigerData credentials.

So:

- `sa.kedardeshmukh.com` can serve the static UI.
- The actual analysis requires running the local Python server.
- DB credentials are loaded server-side from `.env` and are not sent to the browser or committed to git.

## Local Run Instructions

From the repo root:

```bash
cd "/Users/kedar/Desktop/Soiling Context & Code/soiling_analysis"
PYTHONPATH=. /opt/anaconda3/bin/python3 -m soiling_analysis.web_server --host 0.0.0.0 --port 8765
```

Then open:

```text
http://localhost:8765/
```

The app was verified locally at `http://localhost:8765/`.

## Environment

The analysis server expects TigerData credentials via environment variables or `.env`:

```text
TIGERDATA_HOST=
TIGERDATA_PORT=
TIGERDATA_DB=
TIGERDATA_USER=
TIGERDATA_PASSWORD=
TIGERDATA_SSLMODE=require
TIGERDATA_CONNECT_TIMEOUT=10
```

The server currently checks:

- `.env` in the current working directory
- `.env` in the repo root
- `.env` in the parent directory

The real `.env` is intentionally ignored by git.

## Verification Performed

Unit tests:

```bash
PYTHONPATH=. /opt/anaconda3/bin/python3 -m pytest
```

Result:

```text
14 passed
```

Real API smoke test was run with:

- Plant: `b0000000-0000-0000-0000-000000000002`
- Inverter: `ACB01-INV05`
- String port: `4`
- Window: `2026-02-15` to `2026-05-05`
- IQR alpha: `5`

Observed output:

- 78 days loaded
- 5 detected cleaning events
- 4 segments
- 2 reliable segments
- Overall rate: approximately `0.0509 %/day`

## GitHub Pages / DNS

GitHub Pages is configured and built, but `sa.kedardeshmukh.com` still needs DNS.

At GoDaddy, add:

```text
Type:  CNAME
Name:  sa
Value: KedarREGird.github.io
```

After DNS propagates, revisit GitHub repo settings:

```text
Settings > Pages
```

Then enable:

```text
Enforce HTTPS
```

## Key Files

- `index.html` - web interface
- `styles.css` - web UI styling
- `soiling_analysis/web_server.py` - local HTTP server and API routes
- `soiling_analysis/analysis.py` - single-string analysis orchestration
- `soiling_analysis/cleaning_events.py` - cleaning-event detection/classification
- `soiling_analysis/hampel.py` - Hampel filter
- `soiling_analysis/soiling_rate.py` - segmentation, Prophet trend fitting, and rate aggregation
- `soiling_analysis/env.py` - `.env` loading and DB connection kwargs
- `CNAME` - GitHub Pages custom domain

## Caution

Do not commit:

- `.env`
- notebooks
- exported data
- database dumps
- generated caches

The `.gitignore` already excludes `.env`, `notebooks/`, caches, and build artifacts.
