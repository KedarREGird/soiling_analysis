# Soiling Analysis — Logical Workflow, Inputs & Outputs

Reference document for the three Jupyter notebooks in this folder:

- `Hampel Filter implementation.ipynb`
- `Non-Uniform Soiling.ipynb`
- `Shadow Filtering.ipynb`

Backed by the two PDFs in this folder:

- *A data-driven approach to automate cleaning event detection* — the SRR-based cleaning-event detection method.
- *Estimation of non-uniform soiling loss in a utility-scale PV plant in India* — the FBP-based per-string soiling-rate method.

---

## 1. Pipeline Overview

Two independent tracks. The **PR track** (daily granularity) is a hard chain: Hampel filtering feeds the non-uniform soiling estimator. The **power track** (hourly granularity) is a parallel anomaly-detection pipeline that does not currently feed into the soiling estimator.

```
                    ┌───────────────────────────┐
  Daily PR + Rain → │ 1. Hampel Filter          │ → cleaned PR + CE flags
                    │    (PR.csv)               │   (CSV, plots)
                    └─────────────┬─────────────┘
                                  │ filtered PR, CE dates
                                  ▼
                    ┌───────────────────────────┐
  Daily PR (per-   →│ 2. Non-Uniform Soiling    │ → soiling rate (%/day)
  string median)    │    segment + FBP trend    │   per interval + overall
                    │    (Median PR.csv)        │
                    └───────────────────────────┘

  Hourly power +    ┌───────────────────────────┐
  GHI / DHI / T  → │ 3. Shadow Filtering       │ → anomaly-flagged power
  + wind            │    pvlib model vs. meas.  │   train/test CSVs, plots
                    │    (67-Site_DKA-...csv)   │
                    └───────────────────────────┘
```

### 1a. Notebook 1 — Hampel Filter (logical steps)

1. **Load & index** daily PR CSV; parse `timestamp`, forward-fill gaps.
2. **Initial outlier scan** — rolling median (window = 6) + IQR rule with α = 1.1 to surface candidate cleaning days.
3. **Hampel filter** — `hampel_filter_forloop(series, window_size=7, n_sigmas=1)` using MAD scale `k = 1.4826`; outliers replaced with NaN, then forward-filled.
4. **Refined CE detection** — rolling median (window = 11) on the filtered series, IQR rule with α = 0.9, collect dates `Y` and indices `Y2`.
5. **Build CE flags** — `ra-CE = (Rain > 1 mm)`, `log-CE = (date ∈ logged-cleaning list)`.
6. **Export** to `CE automation/PR-rain.csv`; render diagnostic plots (PR vs. filtered PR, monthly box plots, distribution fit, daily POA insolation).

### 1b. Notebook 2 — Non-Uniform Soiling (logical steps)

1. **Load & index** `Median PR.csv` (per-string daily median PR).
2. **Hampel filter** — same function and parameters as Notebook 1 (re-implemented inline).
3. **CE detection** — rolling median (window = 7) with IQR rule and α = 7 (site-tuned aggressive threshold).
4. **Segment** — split the PR series into intervals between consecutive CE indices, producing parallel lists `A` (PR), `B` (indices), `C` (dates); deduplicate.
5. **Length filters** — drop segments with length ≤ 2 days; for segments shorter than 11 days, flatten to a constant profile.
6. **Trend fit** — `fbp(D, Y)` calls Facebook Prophet (`n_changepoints=50`, `changepoint_range=1`, seasonality off) on each segment, returning the fitted trend `D2`.
7. **Per-segment soiling rate** — `np.diff(D2[i])` rounded to 4 dp; weight unique decline values by frequency to get `rate2[i]` (%/day).
8. **Reliability filter & aggregation** — keep segments with length ≥ 14 days; overall rate = Σ(`SRate × Length`) / Σ(`Length`).

### 1c. Notebook 3 — Shadow Filtering (logical steps)

1. **Load & restrict** hourly site CSV to the study window (e.g. 2010-06-01 → 2016-05-31).
2. **Solar position** — `pvlib.location.Location.get_solarposition()` with auto-timezone (`timezonefinder`).
3. **POA irradiance** — ERBS decomposition of GHI, then `irradiance.beam_component(tilt=20, azimuth=0, …)` + `irradiance.isotropic(tilt=20, DHI)`.
4. **Module temperature & expected DC power** — `pvlib.temperature.sapm_module(params=(-3.56, -0.075))` then `pvlib.pvsystem.pvwatts_dc(temp_coeff=-0.002, T_ref=25 °C)` → modeled power `MP`.
5. **Error series** — `diff = |MP − Active_Power|`, restricted to the 9 AM–3 PM window.
6. **Anomaly flag** — daily `med-diff = diff.resample('D').median()`; flag rows where `diff ≥ 2 × med-diff` into the `ano` column.
7. **Split & export** — emit `2010_test.csv`, `2015_test.csv`, `2011-2014 (Shadow study).csv`; render measured-vs-modeled plot with anomaly markers.

---

## 2. Inputs (consolidated)

### 2a. Data files

| Source notebook | File | Granularity | Purpose |
|---|---|---|---|
| Hampel | `PR.csv` | Daily | Temperature-corrected PR + rainfall for one string |
| Non-Uniform Soiling | `Median PR.csv` | Daily | Per-string daily median PR (already temperature-corrected) |
| Shadow Filtering | `67-Site_DKA-M8_A-Phase.csv` | Hourly | Measured AC power, irradiance, weather (DKA Solar Centre, Alice Springs) |

### 2b. Required CSV columns

| File | Column | Type | Meaning |
|---|---|---|---|
| `PR.csv` | `timestamp` | datetime | Day index |
| `PR.csv` | `PR` | float | Daily temperature-corrected performance ratio |
| `PR.csv` | `Rain` | float (mm) | Daily rainfall |
| `Median PR.csv` | `Date` | datetime | Day index |
| `Median PR.csv` | `'0'` | float | Daily median PR for the target string |
| Hourly site CSV | `timestamp` | datetime (`%Y-%m-%d %H:%M`) | Hour index |
| Hourly site CSV | `Active_Power` | float (kW) | Measured AC power |
| Hourly site CSV | `Global_Horizontal_Radiation` | float (W/m²) | GHI |
| Hourly site CSV | `Diffuse_Horizontal_Radiation` | float (W/m²) | DHI |
| Hourly site CSV | `Weather_Temperature_Celsius` | float (°C) | Ambient temperature |
| Hourly site CSV | `Wind_Speed` | float (m/s) | Wind speed |
| Hourly site CSV | `Radiation_Global_Tilted` | float (W/m²) | Tilted-plane irradiance (optional, dropped) |
| Hourly site CSV | `Radiation_Diffuse_Tilted` | float (W/m²) | Tilted-plane diffuse (optional, dropped) |

### 2c. Site / plant metadata (hard-coded inside the notebooks)

| Source notebook | Parameter | Example value |
|---|---|---|
| Hampel | Plant | NTPC Kerala, ICR1-INV2, SMB15, String 2 |
| Hampel | Study window | 2022-02-11 → 2023-03-01 |
| Hampel | Logged cleaning dates | manually-listed reference set |
| Non-Uniform Soiling | Plant | South India, ICR1, INV2, SMB8, String 2 |
| Non-Uniform Soiling | Study window | ~3 months (dry season, 2023) |
| Shadow Filtering | Latitude / Longitude | −23.6980 / 133.874886 |
| Shadow Filtering | Tilt / Azimuth | 20° / 0° (due south) |
| Shadow Filtering | Inverter DC capacity | 4920 W |
| Shadow Filtering | Study window | 2010-06-01 → 2016-05-31 |

### 2d. Algorithm parameters

| Source notebook | Parameter | Value | Meaning |
|---|---|---|---|
| Hampel, Non-Uniform Soiling | `window_size` | 7 | Hampel sliding window (±3 days) |
| Hampel, Non-Uniform Soiling | `n_sigmas` | 1 | MAD multiplier for outlier flag |
| Hampel, Non-Uniform Soiling | `k` | 1.4826 | MAD → σ scale for Gaussian assumption |
| Hampel | Rolling-median windows | 6, 11 | Initial / refined CE scans |
| Hampel | IQR scaling α | 1.1, 0.9 | Initial / refined CE thresholds (`Q3 + α·IQR`) |
| Hampel | Rain threshold | 1 mm/day | `ra-CE` flag |
| Non-Uniform Soiling | Rolling-median window | 7 | CE scan |
| Non-Uniform Soiling | IQR scaling α | 7 | Site-tuned aggressive CE threshold |
| Non-Uniform Soiling | Min segment length | > 2 days | Drop unusably-short intervals |
| Non-Uniform Soiling | Flat-profile threshold | < 11 days | Hold profile constant for very short intervals |
| Non-Uniform Soiling | Reliable-interval cutoff | ≥ 14 days | Inclusion in weighted overall rate |
| Non-Uniform Soiling | FBP `n_changepoints` | 50 | Internal trend break candidates |
| Non-Uniform Soiling | FBP `changepoint_range` | 1 | Allow change points across full segment |
| Non-Uniform Soiling | FBP seasonality | off | Series too short for seasonality |
| Shadow Filtering | Peak-hour window | 09:00–15:00 | Restrict to high-SNR hours |
| Shadow Filtering | Anomaly threshold | `diff ≥ 2 × med-diff` | 2× daily median absolute error |
| Shadow Filtering | SAPM module-temp params | (−3.56, −0.075) | `pvlib.temperature.sapm_module` |
| Shadow Filtering | PVWatts temp coefficient | −0.002 / °C | `pvlib.pvsystem.pvwatts_dc` |
| Shadow Filtering | PVWatts reference temp | 25 °C | `pvlib.pvsystem.pvwatts_dc` |
| Shadow Filtering | POA decomposition | ERBS | `pvlib.irradiance.erbs` |
| Shadow Filtering | Diffuse model | Isotropic | `pvlib.irradiance.isotropic` |

---

## 3. Outputs (consolidated)

| Source notebook | Output | Form | Meaning |
|---|---|---|---|
| Hampel | `df['1']` | pandas Series | Hampel-filtered PR (outliers → NaN) |
| Hampel | `df['2']` | pandas Series | Forward-filled filtered PR |
| Hampel | `Y` | list of dates | Detected cleaning-event dates |
| Hampel | `Y2` | list of int | Detected cleaning-event row indices |
| Hampel | `ra-CE` | binary column | Rain-driven CE flag (`Rain > 1 mm`) |
| Hampel | `log-CE` | binary column | Manually-logged CE flag |
| Hampel | `CE automation/PR-rain.csv` | CSV | Full DataFrame with both CE flag columns |
| Hampel | Diagnostic plots | matplotlib | Daily PR vs. filtered PR, monthly box plots, distribution fit, daily POA insolation vs. rainfall |
| Non-Uniform Soiling | `Y_1`, `Y2` | lists | Detected CE dates / indices |
| Non-Uniform Soiling | `A1`, `B1`, `C1` | parallel lists | Per-segment PR values, indices, dates |
| Non-Uniform Soiling | `D2` | list of arrays | FBP-fitted trend per segment |
| Non-Uniform Soiling | `rate2[i]` | float (%/day) | Weighted decline rate of segment i |
| Non-Uniform Soiling | `s` | DataFrame | Reliable segments (`SRate`, `Length`) with `Length ≥ 14` |
| Non-Uniform Soiling | `rate` | float (%/day) | Overall weighted soiling rate |
| Non-Uniform Soiling | Trend-overlay plot | matplotlib | PR with FBP trends per interval and CE markers |
| Shadow Filtering | `s` | DataFrame | Hourly data + solar position + POA + `MP` (modeled power) + `med-diff` + `ano` (flagged power) |
| Shadow Filtering | `2010_test.csv` | CSV | Anomaly-flagged 2010 records (test set) |
| Shadow Filtering | `2015_test.csv` | CSV | Anomaly-flagged 2015 records (test set) |
| Shadow Filtering | `2011-2014 (Shadow study).csv` | CSV | Training-period anomaly records |
| Shadow Filtering | Measured-vs-modeled plot | matplotlib | Normalised AC power, modeled power, anomaly markers over a 5-day window |

---

## 4. Notebook Dependencies

- **Hampel → Non-Uniform Soiling** is the only hard dependency. Non-Uniform Soiling assumes the same daily, temperature-corrected PR shape that Hampel cleans, and re-implements `hampel_filter_forloop` inline rather than importing it. If Hampel's filter or threshold conventions change, Non-Uniform Soiling must be updated to match.
- **Shadow Filtering** is independent. It operates on hourly power and weather data, produces its own anomaly-flagged CSVs, and is not consumed by the soiling-rate estimator in the current code.
- *Observation (not in scope here)*: the duplicated Hampel implementation across the two PR notebooks is a refactor candidate.

---

## 5. Verification / How to Run

1. **Inputs in place** — confirm the three CSVs exist at the paths referenced near the top of each notebook (or update the paths). Spot-check that the required columns listed in §2b are present and parseable as datetimes / floats.
2. **Run top-to-bottom** in Jupyter:
   - **Hampel**: diagnostic plot of raw vs. filtered PR renders; `CE automation/PR-rain.csv` is written; `Y` (detected CE dates) is non-empty.
   - **Non-Uniform Soiling**: trend-overlay plot renders with one FBP trend per inter-cleaning segment; final cell prints the overall weighted soiling rate as a float in %/day.
   - **Shadow Filtering**: the three CSVs (`2010_test.csv`, `2015_test.csv`, `2011-2014 (Shadow study).csv`) are written; the 5-day measured-vs-modeled plot renders with anomaly markers visible.
3. **Sanity checks**:
   - Cross-check Hampel's `ra-CE` (rain-driven) and `log-CE` (manually-logged) flags against the algorithmically-detected `Y`. A site with very different noise should be re-tuned via the IQR α (1.1 / 0.9 in Hampel; 7 in Non-Uniform Soiling).
   - In Shadow Filtering, confirm the 9 AM–3 PM restriction is applied before the anomaly flag is computed; otherwise low-irradiance hours dominate `med-diff` and the threshold becomes too lax.
   - Confirm Non-Uniform Soiling drops segments shorter than 14 days from the overall-rate aggregation; otherwise short, noisy intervals can swing the headline number.
