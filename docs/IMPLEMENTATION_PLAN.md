# Implementation Plan — Soiling Algorithm for Shambhavi Green Energy

Companion to `WORKFLOW.md` and `PARAMETER_MAPPING.md`. This copy has been
adapted for the standalone `soiling_analysis` repo.

## Context

The soiling notebooks in this folder demonstrate per-string soiling-rate
extraction on offline CSV exports. Shambhavi (10 MW AC / 13 MWp DC, 61
inverters × 24 active strings × 27 modules, 18° tilt, 180° azimuth, Risen
RSM144-6-440P modules, Huawei WP-330KTL-H1 inverters) now has continuous
telemetry in TimescaleDB. The goal is to run the Hampel → cleaning-event
detection → Prophet-segmented soiling-rate pipeline as a scheduled service
reading from the DB and writing per-string daily soiling rates back into
the DB, so O&M can act on the output.

### Confirmed decisions

1. **POA reference model:** Hay-Davies (`models.irradiance.transposition_model = "haydavies"`) — consistent with the digital twin already running for Shambhavi.
2. **CE detection IQR scaling:** bootstrap with **α = 2** for Shambhavi and tune once O&M logs ground-truth cleanings through the new API.
3. **Backfill window:** start from the earliest reliable telemetry for Shambhavi (heuristic in §6.1 — first 30-day window where ≥ 80 % of expected 15-min rows are present across all 61 inverters).

## Architecture overview

```
   weather_data         ┐
   inverter_readings    ├─► [Phase 1: SQL]                ┐
   string_readings      │   daily_string_yield (matview)  │
   inverter_analysis    │   daily_string_pr (matview)     │
                        │                                 ├─► [Phase 3: storage]
                        │                                 │   cleaning_events (table)
                        ├─► [Phase 2: Python service]     │   daily_string_soiling (table)
                        │   services/intelligence/        │   POST /cleaning-events (API)
                        │   soiling_analysis/             │
                        │     hampel.py                   │
                        │     cleaning_events.py          │
                        │     soiling_rate.py             │
                        │     run.py (entrypoint)         ┘
```

Three phases, each independently shippable.

---

## Phase 1 — SQL data prep (no new algorithms)

Goal: materialise the two daily, per-string tables the notebook math
already assumes exist. Adds two TimescaleDB continuous aggregates
(refresh nightly).

### 1.1 Migration `035_create_daily_string_yield.py`

Location: `database/alembic/versions/035_create_daily_string_yield.py`

Creates **`daily_string_yield`** as a TimescaleDB continuous aggregate
over `string_readings`:

```sql
SELECT
  time_bucket('1 day', time) AS date,
  plant_id,
  inverter_id,
  asset_id AS string_asset_id,
  string_number,
  -- Daily DC energy: integrate V·I over 15-min buckets, sum to day
  SUM(voltage_v * current_a * 0.25) / 1000.0 AS yield_kwh
FROM string_readings
WHERE voltage_v IS NOT NULL AND current_a IS NOT NULL
GROUP BY 1, 2, 3, 4, 5;
```

Refresh policy: nightly, lookback 3 days.

### 1.2 Migration `036_create_daily_string_pr.py`

Location: `database/alembic/versions/036_create_daily_string_pr.py`

Creates **`daily_string_pr`** as a regular materialised view joining:
- `daily_string_yield` (this phase's output)
- `inverter_analysis.poa_irradiance_w_sqm` (already exists, migration 030)
  resampled to daily PSH: `SUM(poa_irradiance_w_sqm) / 4 / 1000` (15-min → kWh/m²)
- `inverter_analysis.temp_cell_c` (already exists, migration 029) averaged to
  daily-weighted mean (weighted by `poa_irradiance_w_sqm`)
- `plant_assets` → `module_types` (for `pdc0_w`, `gamma_pmp`)

PR formula (closes `PARAMETER_MAPPING.md` §3 gap 1 — temperature correction):

```
capacity_kwp        = string.module_count × module_types.pdc0_w / 1000
PR_uncorrected      = yield_kwh / (capacity_kwp × PSH)
PR_temp_corrected   = PR_uncorrected / (1 + gamma_pmp_per_C × (T_cell_avg - 25))
```

For Shambhavi: `capacity_kwp = 27 × 440 / 1000 = 11.88 kWp` per string;
`gamma_pmp = -0.41 %/°C` for Risen RSM144-6-440P (negative coefficient,
so warmer cells → smaller divisor → higher corrected PR).

Output columns: `date, plant_id, inverter_id, string_asset_id, string_number,
yield_kwh, psh, t_cell_avg_c, capacity_kwp, pr_uncorrected, pr_corrected`.

Refresh policy: nightly, lookback 3 days.

### 1.3 Backfill heuristic (used by Phase 2 entrypoint)

Function `find_earliest_reliable_date(plant_id)` in
`services/intelligence/soiling_analysis/data_quality.py`:

```
For each 30-day window starting at the earliest string_readings.time:
  expected_rows = 30 × 96 × n_strings              # 96 = 15-min buckets/day
  actual_rows   = COUNT(*) WHERE plant_id, range
  if actual_rows / expected_rows >= 0.80:
    return window start date
```

Persist the resolved start date in `plants.metadata.soiling_backfill_start`
on first run so reruns are idempotent.

---

## Phase 2 — Python service

New service tree, mirrors `data_analysis_pipeline/`:

```
soiling_analysis/
├── __init__.py
├── config.py                  # tunables (α, window sizes, segment thresholds)
├── data_quality.py            # find_earliest_reliable_date(...)
├── hampel.py                  # hampel_filter(series, window_size=7, n_sigmas=1)
├── cleaning_events.py         # detect_cleaning_events(...), classify_source(...)
├── soiling_rate.py            # segment_intervals(...), fit_segment(...), aggregate(...)
├── repository.py              # read_daily_string_pr / write_results SQL
├── run.py                     # CLI entrypoint: python -m soiling_analysis.run --plant <uuid>
└── tests/
    ├── test_hampel.py
    ├── test_cleaning_events.py
    └── test_soiling_rate.py
```

### 2.1 `config.py`

```python
# services/intelligence/soiling_analysis/config.py
from pydantic import BaseModel

class SoilingConfig(BaseModel):
    # Hampel — from Notebooks 1 & 2
    hampel_window_size: int = 7
    hampel_n_sigmas: int = 1
    hampel_k_mad: float = 1.4826

    # Cleaning event detection — α=2 bootstrap for Shambhavi
    ce_rolling_median_window: int = 7
    ce_iqr_alpha: float = 2.0
    ce_rain_threshold_mm: float = 1.0

    # Segmentation
    min_segment_length_days: int = 3
    flat_profile_threshold_days: int = 11
    reliable_interval_min_days: int = 14

    # Prophet
    fbp_n_changepoints: int = 50
    fbp_changepoint_range: float = 1.0
    fbp_seasonality: bool = False

DEFAULT_CONFIG = SoilingConfig()
```

All values exposed here, **not hardcoded** — closes `PARAMETER_MAPPING.md`
§3 gap 8.

### 2.2 `hampel.py`

Single implementation, both notebooks today duplicate this:

```python
def hampel_filter(series: pd.Series, window_size: int = 7, n_sigmas: int = 1) -> pd.Series:
    """Replace outliers with NaN. MAD scale k = 1.4826."""
```

Forward-fill is the caller's responsibility (different callers want
different fill strategies).

### 2.3 `cleaning_events.py`

```python
def detect_cleaning_events(pr_series: pd.Series, cfg: SoilingConfig) -> list[date]:
    # 1. hampel_filter -> ffill
    # 2. rolling median (window=cfg.ce_rolling_median_window)
    # 3. day-to-day diff, IQR rule: out = Q3 + α × IQR
    # 4. return dates where diff > out

def classify_source(ce_dates, rainfall_daily, logged_dates) -> pd.DataFrame:
    # Returns DataFrame with columns: date, source ∈ {algorithm, rainfall, logged, both}
```

### 2.4 `soiling_rate.py`

```python
def segment_intervals(pr_series, ce_dates, cfg) -> list[Segment]
def fit_segment(segment, cfg) -> np.ndarray   # Prophet trend
def segment_soiling_rate(trend) -> float       # %/day
def aggregate_overall(segments, cfg) -> float  # weighted mean over length>=14d
```

`fit_segment` wraps Prophet with the three notebook params from `config.py`.
For segments shorter than `flat_profile_threshold_days`, return a flat
profile (matches notebook behaviour).

### 2.5 `repository.py`

```python
def load_string_pr(conn, plant_id, start_date, end_date) -> dict[string_asset_id, pd.DataFrame]
def load_rainfall_daily(conn, plant_id, start_date, end_date) -> pd.Series
def load_logged_cleanings(conn, plant_id, start_date, end_date) -> list[date]   # from cleaning_events table, source='logged'
def write_cleaning_events(conn, plant_id, events: pd.DataFrame)
def write_string_soiling(conn, plant_id, results: pd.DataFrame)
```

Uses `.env` / environment variables named `TIGERDATA_*`.

### 2.6 `run.py`

```
python -m soiling_analysis.run \
    --plant <shambhavi-uuid> \
    [--start-date YYYY-MM-DD]   # default: find_earliest_reliable_date or plants.metadata.soiling_backfill_start
    [--end-date YYYY-MM-DD]     # default: yesterday
    [--config path/to/yaml]     # default: built-in SoilingConfig()
```

Pipeline:
1. Resolve date window via `data_quality.find_earliest_reliable_date` (first run) or `plants.metadata.soiling_backfill_start` (subsequent).
2. For each active string of the plant, `repository.load_string_pr` → `hampel_filter` → `detect_cleaning_events` → `classify_source` (join rainfall + logged) → `segment_intervals` → per-segment Prophet fit → per-string overall rate.
3. Batch insert into `cleaning_events` (source='algorithm') and `daily_string_soiling`.
4. Log per-plant summary: # events detected, # rain-explained, # logged-confirmed, mean soiling rate.

---

## Phase 3 — Storage tables and ops layer

### 3.1 Migration `037_create_cleaning_events.py`

Location: `database/alembic/versions/037_create_cleaning_events.py`

```sql
CREATE TABLE cleaning_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plant_id        UUID NOT NULL REFERENCES plants(id),
    asset_id        UUID REFERENCES plant_assets(id),   -- nullable: plant-wide events
    date            DATE NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('algorithm','rainfall','logged','both')),
    confidence      NUMERIC(4,3),                       -- 0–1, nullable for logged
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    notes           TEXT,
    UNIQUE (asset_id, date, source)
);
CREATE INDEX ON cleaning_events (plant_id, date);
CREATE INDEX ON cleaning_events (asset_id, date);
```

Closes `PARAMETER_MAPPING.md` §3 gap 3 (no cleaning-event log table).

### 3.2 Migration `038_create_daily_string_soiling.py`

Location: `database/alembic/versions/038_create_daily_string_soiling.py`

```sql
CREATE TABLE daily_string_soiling (
    asset_id            UUID NOT NULL REFERENCES plant_assets(id),
    date                DATE NOT NULL,
    pr_corrected        NUMERIC(5,4),
    pr_filtered         NUMERIC(5,4),                  -- after Hampel + ffill
    segment_id          INT,                            -- 1..N within plant within calendar year
    segment_length_days INT,
    soiling_rate_pct_per_day NUMERIC(6,4),
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (asset_id, date)
);
CREATE INDEX ON daily_string_soiling (date);
```

### 3.3 Cleaning-events API endpoint

Location: `services/api/routes/cleaning_events.py` (mirroring whatever
route style the existing API service uses — confirm with the API service
maintainer before merging).

- `POST /cleaning-events` — O&M logs a manual cleaning. Body:
  `{plant_id, asset_id?, date, notes?}` → writes row with `source='logged'`.
- `GET /cleaning-events?plant_id=…&start=…&end=…` — returns merged
  algorithm + rainfall + logged events for a window.

This is what unblocks tuning α in decision (2): once O&M starts logging,
`source='logged'` rows give F1-score ground truth.

### 3.4 Schedule

Add to `scripts/run_soiling_nightly.sh` (cron at 02:30 IST nightly, after the
existing `daily_inverter_analysis` job at 01:00):

```bash
python -m soiling_analysis.run --plant $SHAMBHAVI_PLANT_UUID
```

Add `SHAMBHAVI_PLANT_UUID` to `.env.example` with placeholder.

---

## Files touched

### New files
- `database/alembic/versions/035_create_daily_string_yield.py`
- `database/alembic/versions/036_create_daily_string_pr.py`
- `database/alembic/versions/037_create_cleaning_events.py`
- `database/alembic/versions/038_create_daily_string_soiling.py`
- `services/intelligence/soiling_analysis/__init__.py`
- `services/intelligence/soiling_analysis/config.py`
- `services/intelligence/soiling_analysis/data_quality.py`
- `services/intelligence/soiling_analysis/hampel.py`
- `services/intelligence/soiling_analysis/cleaning_events.py`
- `services/intelligence/soiling_analysis/soiling_rate.py`
- `services/intelligence/soiling_analysis/repository.py`
- `services/intelligence/soiling_analysis/run.py`
- `services/intelligence/soiling_analysis/tests/test_hampel.py`
- `services/intelligence/soiling_analysis/tests/test_cleaning_events.py`
- `services/intelligence/soiling_analysis/tests/test_soiling_rate.py`
- `services/api/routes/cleaning_events.py` (or equivalent — confirm path)
- `scripts/run_soiling_nightly.sh`

### Existing files modified
- `.env.example` — add `SHAMBHAVI_PLANT_UUID`
- `pyproject.toml` — add `prophet` dependency (pinned)
- `libs/superpower_common/models/__init__.py` — export new `CleaningEvent`,
  `DailyStringSoiling` SQLAlchemy / pydantic models (mirroring
  `telemetry.py` / `weather.py` style)
- `libs/superpower_common/models/soiling.py` — new model file for the
  two new tables

### Not modified (deliberately)
- `models/telemetry.py`, `models/weather.py` — schemas unchanged
- `services/intelligence/digital_twin/` — Hay-Davies stays the POA model
- `services/intelligence/data_analysis_pipeline/analysis/pr_calc.py` — left
  in place; the soiling service produces its own temperature-corrected PR
  rather than rewriting the existing inverter-level PR

---

## Verification

### Unit tests (run in CI)
- `test_hampel.py` — feed a synthetic series with three injected spikes at
  known indices, assert all three flagged with `window=7, n_sigmas=1`.
- `test_cleaning_events.py` — feed a synthetic PR series with step changes
  on known dates, assert detection at α=2 returns exactly those dates.
- `test_soiling_rate.py` — feed a known linear decline of 0.05 %/day across
  a 30-day segment, assert the aggregated rate is within ±0.005 %/day.

### Integration test (manual, run once on staging)
1. Apply migrations 035–038 against a staging copy of the Shambhavi DB.
2. Confirm `daily_string_yield` populates for the first 7 days
   (`SELECT COUNT(DISTINCT string_asset_id) FROM daily_string_yield` should
   return ≈ 61 × 24 = 1,464).
3. Confirm `daily_string_pr.pr_corrected` falls in a plausible range
   (0.6–0.9) for a clear-sky week.
4. Run the entrypoint for one inverter only:
   ```
   python -m soiling_analysis.run \
       --plant $SHAMBHAVI_PLANT_UUID --start-date 2025-01-01 --end-date 2025-03-31
   ```
   Check stdout summary: cleaning events detected, fraction explained by
   rainfall (target: ≥ 50 % of detected events fall within ±1 day of a
   day where `rainfall.resample('D').sum() ≥ 1 mm`).
5. Plot one string's `pr_corrected` and overlay detected events from
   `cleaning_events` for visual sanity — should look like the Notebook 2
   "trend-overlay plot" from `WORKFLOW.md` §3.

### End-to-end (after Phase 3 ships)
1. Run nightly cron for one week on Shambhavi.
2. Have O&M log one real cleaning via the new `POST /cleaning-events`
   endpoint; verify it appears in `GET` results with `source='logged'`.
3. Compare the algorithm's detected events for that week against the
   logged event; if F1 < 0.5, raise α from 2 toward 3–5 (Notebook 2
   used 7 for its specific site).
4. After 30 days of co-logging, compute F1-score on (algorithm vs.
   logged) and pin α via a small grid search (α ∈ {1, 2, 3, 5, 7})
   recorded in `plants.metadata.soiling_iqr_alpha` per plant.

### Rollback
Each migration is reversible. Drop new tables in reverse order:
`038 → 037 → 036 → 035`. Service code removal is a single directory
delete plus removing the cron line and the `prophet` dependency.

---

## Out of scope (intentionally)

- Per-MPPT (not per-string) soiling — the data is there, but the notebook
  algorithm is string-level and the Shambhavi config has 24 active strings
  across 6 MPPTs; adding MPPT aggregation is a follow-up.
- Soiling-aware cleaning-schedule optimisation (the "zone-optimised" /
  "string-optimised" cleaning strategies from the
  *Estimation of non-uniform soiling loss* paper) — this needs the
  soiling-rate output first; treat it as Phase 4.
- Porting Shadow Filtering (Notebook 3) — that pipeline targets a
  different anomaly category (partial shading vs. soiling) and is
  hourly, not daily. Separate workstream.
- Recomputing historical `daily_inverter_analysis.pr_percentage` with
  temperature correction — left as-is; the soiling service produces its
  own corrected PR in `daily_string_pr` and `daily_string_soiling`.
