# superpower-systems-main → Soiling Code: Parameter Mapping

Companion to `WORKFLOW.md`. Inventories the configuration / domain parameters in
`superpower-systems-main/` and maps each soiling-notebook parameter to its
counterpart (or flags it as missing).

Repo paths in this document are relative to
`/Users/kedar/Desktop/Soiling Context & Code/superpower-systems-main/`.

---

## 1. Parameter Inventory — superpower-systems-main

### 1.1 Plant / site metadata (`plants` table)

| Parameter | Location | Type / units | Example | Description |
|---|---|---|---|---|
| `plants.id` | `database/alembic/versions/001_plant_config_tables.py:30` | UUID | `gen_random_uuid()` | Plant identifier |
| `plants.name` | `001_plant_config_tables.py:34` | text | "Shambhavi Green Energy" | Plant name |
| `plants.location` | `001_plant_config_tables.py:35` | text | "Belkund, Latur" | Location descriptor |
| `plants.capacity_mw` | `001_plant_config_tables.py:36` | float MW | 10 | AC nameplate capacity |
| `plants.capacity_dc_mwp` | `020_plant_specs_and_inverter_efficiency.py:29` | float MWp | 13 | DC rated capacity |
| `plants.latitude` | `014_extend_plants_and_devices.py` | float ° | — | Site latitude |
| `plants.longitude` | `014_extend_plants_and_devices.py` | float ° | — | Site longitude |
| `plants.elevation_m` | `014_extend_plants_and_devices.py:21` | float m | 0 | Elevation above sea level |
| `plants.timezone` | `014_extend_plants_and_devices.py:20` | text (IANA) | "Asia/Kolkata" | Plant timezone |
| `plants.tilt_deg` | `014_extend_plants_and_devices.py:22` | float ° | 18 | Array tilt |
| `plants.azimuth_deg` | `014_extend_plants_and_devices.py:23` | float ° | 180 | Array azimuth (0=N, 180=S) |
| `plants.albedo` | `014_extend_plants_and_devices.py:24` | float 0–1 | 0.20 | Ground reflectance |
| `plants.metadata` | `020_plant_specs_and_inverter_efficiency.py:28` | JSONB | `{total_modules, pitch_m, …}` | Layout / physical metadata |

### 1.2 Inverter & string topology (`plant_assets`)

| Parameter | Location | Type | Example | Description |
|---|---|---|---|---|
| `inverter.esn` | `001_plant_config_tables.py:44` | varchar(50) | "1024C9118645" | SmartLogger equipment serial |
| `inverter.make` / `inverter.model` | `001_plant_config_tables.py:45–46` | text | "Huawei" / "WP-330KTL-H1" | Inverter vendor / model |
| `string.number` | `001_plant_config_tables.py:55` | smallint | 1–28 | String port on inverter |
| `string.module_count` | `001_plant_config_tables.py:56` | smallint | 27 | Modules per string |
| `asset.metadata.modules_per_string` | `services/intelligence/digital_twin/solar_digital_twin/core/config_loader.py:99` | int | 27 | Modules in series per string |
| `asset.metadata.active_string_count` | `config_loader.py:100` | int | 24 | Active strings per inverter |
| `asset.metadata.mppt_count` | `database/alembic/versions/025_populate_mppt_number.py:82` | int | 6 | MPPTs per inverter |
| `asset.metadata.mppt_number` | `025_populate_mppt_number.py:68` | int | 1–6 | MPPT bus this string belongs to |
| `asset.metadata.inverter_port` | `024_populate_string_port_metadata.py:41` | int | 1–28 | Physical port number |
| `asset.metadata.port_status` | `024_populate_string_port_metadata.py:51` | enum | 'active' / 'inactive' | Port activity (peak-hour ≥ 0.5 A mean) |
| `asset.metadata.tilt_deg` / `azimuth_deg` | `026_populate_string_module_tilt_azimuth.py:41–42` | float ° | 18 / 180 | String-level tilt/azimuth (inherits plant) |

### 1.3 Module electrical specs (`module_types`)

| Parameter | Location | Type / units | Description |
|---|---|---|---|
| `module_types.name` | `database/alembic/versions/013_create_module_types.py:20` | text | e.g. "Risen RSM144-6-440P" |
| `pdc0_w` | `013_create_module_types.py:21` | float W | STC nameplate (e.g. 440) |
| `voc_v`, `vmp_v` | `013_create_module_types.py:22–23` | float V | Open-circuit / MPP voltage |
| `isc_a`, `imp_a` | `013_create_module_types.py:24–25` | float A | Short-circuit / MPP current |
| `gamma_pmp` | `013_create_module_types.py:26` | %/°C | Pmp temp coefficient |
| `beta_voc` | `013_create_module_types.py:27` | %/°C | Voc temp coefficient |
| `alpha_isc` | `013_create_module_types.py:28` | %/°C | Isc temp coefficient |
| `technology` | `013_create_module_types.py:29` | text | "monoSi" |
| `cells_in_series` | `013_create_module_types.py:30` | int | 144 |
| `cable_loss_frac` | `config_loader.py:118` | float 0–1 | DC cabling loss fraction |
| `inverter.metadata.ac_rating_w` | `config_loader.py:126` | float W | Inverter AC rating (e.g. 330000) |
| `inverter.metadata.eta_inv_nom` | `020_plant_specs_and_inverter_efficiency.py:41` | float | 0.9903 | Nominal inverter efficiency |
| `inverter.metadata.eta_inv_ref` | `020_plant_specs_and_inverter_efficiency.py:41` | float | 0.988 | European (part-load) efficiency |

### 1.4 Telemetry schemas

**`inverter_readings` (15-min hypertable)** — `libs/superpower_common/models/telemetry.py`

| Column | Line | Type / units | Description |
|---|---|---|---|
| `time` | 12 | datetime tz | Reading timestamp |
| `plant_id`, `asset_id`, `smartlogger_esn`, `inverter_number` | 13–16 | identifiers | Routing |
| `uac1_v` … `uac3_v` | 19–21 | float V | AC phase voltages |
| `iac1_a` … `iac3_a` | 24–26 | float A | AC phase currents |
| `pac_kw` | 29 | float kW | Total AC power |
| `qac_kvar` | 30 | float kVAr | Reactive power |
| `eac_kwh` | 33 | float kWh | Cumulative energy |
| `e_day_kwh` | 34 | float kWh | Daily energy counter |
| `e_total_kwh` | 35 | float kWh | Lifetime cumulative |
| `frequency_hz` | 38 | float Hz | Grid frequency |
| `power_factor` | 39 | float | Power factor |
| `temperature_c` | 42 | float °C | Inverter case temperature |
| `status_code`, `error_code` | 45–46 | int | Inverter state codes |

**`string_readings` (15-min hypertable)** — `libs/superpower_common/models/telemetry.py:62–68`
columns: `time`, `plant_id`, `inverter_id`, `asset_id`, `string_number`, `voltage_v`, `current_a`.

**`weather_data` (hourly hypertable)** — `libs/superpower_common/models/weather.py`

| Column | Line | Type / units | Description |
|---|---|---|---|
| `timestamp` | 11 | datetime tz | Hour index |
| `plant_id`, `latitude`, `longitude` | 12–14 | identifiers | Routing |
| `solar_irradiance` | 17 | float W/m² | **GHI** |
| `direct_normal_irradiance` | 18 | float W/m² | **DNI** |
| `diffuse_radiation` | 19 | float W/m² | **DHI** |
| `temperature_2m` | 22 | float °C | Ambient temperature at 2 m |
| `wind_speed` | 23 | float m/s | Wind speed |
| `rainfall` | 24 | float mm/h | Hourly rainfall |
| `pm10`, `pm2_5` | 27–28 | float µg/m³ | Particulate matter |

**`daily_inverter_analysis`** — `database/alembic/versions/016_create_daily_inverter_analysis.py:21–27`
columns: `asset_id`, `date`, `yield_kwh`, **`pr_percentage`**, `clipping_loss_kwh`, `grid_loss_kwh`, `downtime_minutes`.

**`inverter_analysis` (15-min hypertable)** — `database/alembic/versions/029_create_inverter_analysis.py` + `030_add_poa_to_analysis.py:21` + `034_add_pr_to_inverter_analysis.py:19–20`
columns: `time`, `asset_id`, `plant_id`, `sim_pac_kw`, `sim_pdc_kw`, `temp_cell_c`, `yield_kwh`, `clipping_loss_kw`, `grid_loss_kw`, **`poa_irradiance_w_sqm`**, **`measured_pdc_kw`**, **`performance_ratio`**.

### 1.5 Digital twin model parameters

`services/intelligence/digital_twin/config/model.yaml`

| Parameter | Line | Default | Description |
|---|---|---|---|
| `models.irradiance.transposition_model` | 2 | `"haydavies"` | POA transposition (haydavies / isotropic / perez / klucher) |
| `models.effective_irradiance.use_poa_global_directly` | 5 | `true` | Skip spectral correction |
| `models.temperature.model` | 8 | `"pvsyst_cell"` | Cell-temperature model |
| `models.temperature.u_c` | 9 | 29.0 | PVsyst u_c (W/m²·K) |
| `models.temperature.u_v` | 10 | 0.0 | PVsyst u_v (W·s/m³·K) |
| `models.dc.fit_model` | 12 | `"cec"` | Single-diode fit method |
| `models.dc.use_fit_cec_sam` | 13 | `true` | SAM CEC mapping |
| `models.inverter.mode` | 15 | `"pvwatts"` | Inverter loss model |
| `models.inverter.pvwatts.eta_inv_nom` | 17 | 0.985 | Nominal inverter η |
| `models.inverter.pvwatts.eta_inv_ref` | 18 | 0.9637 | Part-load reference η |
| `models.clipping.enable_ac_clip` | 20 | `true` | AC clipping on/off |
| `models.derating.enabled` | 23 | `true` | Thermal derating on/off |
| `models.derating.source_column` | 24 | `inv_temp_c` | Column driving derating |
| `models.derating.start_temp_c` | 25 | 45.0 | Derate start (°C) |
| `models.derating.end_temp_c` | 26 | 60.0 | Derate end (°C) |
| `models.derating.full_power_w` | 27 | 330000 | Pre-derate cap (W) |
| `models.derating.derated_power_w` | 28 | 300000 | Post-derate cap (W) |

### 1.6 Analysis pipeline parameters

`services/intelligence/data_analysis_pipeline/`

| Parameter | Location | Value | Description |
|---|---|---|---|
| PR formula `(yield / (capacity × PSH)) × 100` | `analysis/pr_calc.py:8–17` | derived | DC capacity = strings × modules × `pdc0_w` |
| `clipping.peak_pac_threshold` | `analysis/clipping_loss.py:13` | 0.85 × peak_pac | High-power gate for clipping scan |
| `clipping.flatness_std_threshold` | `analysis/clipping_loss.py:16` | 0.01 × peak_pac | Std-dev gate for flat plateau |
| `clipping.window` | `analysis/clipping_loss.py:16` | `'5min'` | Rolling window for flatness |
| `clipping.min_periods` | `analysis/clipping_loss.py:16` | 3 | Minimum samples in window |
| `grid_loss.daytime_threshold` | `analysis/grid_loss.py:20` | 10 kW | Daytime power floor |
| `SHUTDOWN_ERRORS` | `config.py:5–14` | [2004 … 2110] | Huawei error codes counted as grid loss |
| `yield.source_column` | `analysis/yield_calc.py:5` | `"e_day_kwh"` | Daily energy counter |

### 1.7 Environment / deployment

`libs/superpower_common/config.py`

| Var | Line | Default | Description |
|---|---|---|---|
| `TIGERDATA_HOST` | 29 | `localhost` | TimescaleDB host |
| `TIGERDATA_PORT` | 30 | 5432 | DB port |
| `TIGERDATA_DB` / `_USER` | 31–32 | `tsdb` / `tsdbadmin` | DB name / user |
| `FTP_VM_HOST` | 36 | `34.180.0.79` | SmartLogger FTP VM |
| `FTP_VM_USER` / `FTP_VM_PASSWORD` | 37–38 | `ftpuser` / `ftppswd` | FTP credentials |
| `SMARTLOGGER_BASE_DIR` | 39 | `/home/ftpuser` | FTP base dir |
| `SMARTLOGGER_DIRS` | 40–42 | `[SmartLogger1..4]` | Per-logger subdirs |
| `DT_MODE` | 76 | `local` / `lambda` | Direct call vs. AWS Lambda |
| `DT_LAMBDA_FUNCTION_NAME` | 77 | `digital-twin-engine` | Lambda function name |
| `DT_LAMBDA_REGION` | 78 | `ap-south-1` | Lambda region |

### 1.8 Domain enums

| Enum / constant | Location | Values |
|---|---|---|
| `asset_type` | `008a_create_plant_assets_tables.py:37–41` | transformer · lt_panel · combiner_box · inverter · string · meter · data_logger |
| `port_status` | `024_populate_string_port_metadata.py:51` | active · inactive |
| `SHUTDOWN_ERRORS` | `data_analysis_pipeline/config.py:5–14` | [2004 … 2110] (Huawei codes) |
| Ambient-temp validator | `models/weather.py:45–48` | -60…+60 °C |
| Inverter-temp validator | `models/telemetry.py:64–68` | -40…+120 °C |

---

## 2. Soiling-code → superpower-systems-main mapping

Match quality:
**exact** — same field, same units · **equivalent** — same concept, different shape ·
**approximate** — partial overlap, needs derivation · **no match** — absent in repo.

### 2.1 CSV column mapping

| Soiling notebook column | superpower-systems-main equivalent | Match | Notes |
|---|---|---|---|
| PR.csv `timestamp` | `inverter_readings.time` | exact | datetime with tz |
| PR.csv `PR` | `daily_inverter_analysis.pr_percentage` | exact | % units. Production PR = `(yield_kwh / (capacity_kw × PSH)) × 100` — temperature correction is *not* applied in this formula; see §3 gap (1) |
| PR.csv `Rain` | `weather_data.rainfall` | equivalent | mm/hour in DB; needs daily resample (`.resample('D').sum()`) |
| Median PR.csv `Date` | `daily_inverter_analysis.date` | exact | Date type |
| Median PR.csv `'0'` (median PR) | derived: median over inverters/strings of `inverter_analysis.performance_ratio` | approximate | Per-string daily PR is not stored; must aggregate from `string_readings` (V·I → daily yield) and divide by per-string capacity |
| Hourly `timestamp` | `weather_data.timestamp` / `inverter_readings.time` | exact | — |
| Hourly `Active_Power` | `inverter_readings.pac_kw` | exact | kW |
| Hourly `Global_Horizontal_Radiation` (GHI) | `weather_data.solar_irradiance` | exact | W/m² — naming differs |
| Hourly `Diffuse_Horizontal_Radiation` (DHI) | `weather_data.diffuse_radiation` | exact | W/m² |
| Hourly `Weather_Temperature_Celsius` | `weather_data.temperature_2m` | exact | °C |
| Hourly `Wind_Speed` | `weather_data.wind_speed` | exact | m/s |
| Hourly `Radiation_Global_Tilted` (POA global) | `inverter_analysis.poa_irradiance_w_sqm` | equivalent | Modeled (DT output) rather than measured |
| Hourly `Radiation_Diffuse_Tilted` | DT-internal POA diffuse component | approximate | Computed during DT run but not persisted as a column |

### 2.2 Site-metadata mapping

| Soiling notebook field | superpower-systems-main equivalent | Match | Notes |
|---|---|---|---|
| Plant / string identifier (`ICR1-INV2-SMB15-Str2` etc.) | `plants.id` + `plant_assets` (asset_type='string', `inverter_id`, `string.number`) | equivalent | Hierarchy is normalised; soiling labels need a lookup |
| Latitude | `plants.latitude` | exact | — |
| Longitude | `plants.longitude` | exact | — |
| Tilt (°) | `plants.tilt_deg` (or per-string `asset.metadata.tilt_deg`) | exact | — |
| Azimuth (°) | `plants.azimuth_deg` (or per-string `asset.metadata.azimuth_deg`) | exact | Soiling Shadow Filtering uses 0=south; superpower uses 180=south. Convert. |
| Inverter DC capacity | `strings_per_inverter × modules_per_string × module_types.pdc0_w` | equivalent | Computed in `pr_calc.py`; not stored as a single field |
| Inverter AC capacity | `inverter.metadata.ac_rating_w` | exact | — |
| Study window (start/end dates) | query filter on `inverter_readings.time` / `daily_inverter_analysis.date` | equivalent | No fixed config; provided per-query |
| Logged cleaning dates | — | **no match** | No cleaning-event log table exists; today the data lives in WhatsApp / spreadsheets |
| Timezone | `plants.timezone` | exact | Notebook uses `timezonefinder` from lat/lon; repo stores explicit IANA |

### 2.3 Algorithm-parameter mapping

| Soiling parameter | superpower-systems-main equivalent | Match | Notes |
|---|---|---|---|
| **Hampel filter** `window_size=7` | — | no match | Hampel filter not implemented in services |
| Hampel `n_sigmas=1` | — | no match | — |
| Hampel MAD scale `k=1.4826` | — | no match | — |
| **CE detection** rolling-median window (6 / 7 / 11) | — | no match | Cleaning-event detection not implemented in services |
| CE detection IQR scaling α (0.9 / 1.1 / 7) | — | no match | — |
| Rain threshold `Rain > 1 mm` (ra-CE flag) | — | no match | Rainfall is collected but no CE-flag derivation exists |
| **FBP segmentation** min length > 2 d | — | no match | No FBP / Prophet pipeline |
| FBP flat-profile threshold < 11 d | — | no match | — |
| FBP reliable-interval cutoff ≥ 14 d | — | no match | — |
| FBP `n_changepoints=50`, `changepoint_range=1`, seasonality off | — | no match | — |
| **Shadow filter** peak-hour window 09:00–15:00 | analysis pipeline uses `grid_loss.daytime_threshold = 10 kW` (power-based, not clock-based) | approximate | Different semantics; both filter "daytime" |
| Shadow anomaly threshold `diff ≥ 2 × med-diff` | `clipping.peak_pac_threshold = 0.85 × peak_pac` + `flatness_std_threshold = 0.01 × peak_pac` | approximate | Different anomaly category (clipping vs. shadow) but conceptually the closest |
| Shadow SAPM module-temp params `(-3.56, -0.075)` | `models.temperature.model = "pvsyst_cell"`, `u_c = 29.0`, `u_v = 0.0` | approximate | Different thermal model (PVsyst vs. SAPM); reconciliation needed |
| Shadow PVWatts temp coeff `-0.002 / °C` @ 25 °C | `module_types.gamma_pmp` (per-module datasheet) | equivalent | Stored per module type rather than as a global default |
| Shadow POA decomposition = ERBS | `models.irradiance.transposition_model = "haydavies"` | approximate | Hay-Davies in production, ERBS in notebook — POA values will differ |
| Shadow diffuse model = isotropic | Hay-Davies (default); pvlib supports isotropic but it's not the default | equivalent | Switchable via `transposition_model` |

---

## 3. Gaps & observations

1. **Temperature-corrected PR is not explicit in production.** `daily_inverter_analysis.pr_percentage` uses `yield / (capacity × PSH)`; no documented `T_module → 25 °C` correction. The soiling notebooks assume the input PR is already temperature-corrected. Verify whether `yield_kwh` is corrected upstream or if a correction step needs to be added before notebooks consume DB-side PR.

2. **No per-string daily PR table.** Notebook `'0'` column (median PR per string) requires aggregating `string_readings` (V·I → kWh) and dividing by per-string capacity (`module_count × pdc0_w`). Worth materialising as a `daily_string_analysis` table if soiling analysis becomes recurring.

3. **No cleaning-event log table.** Hampel notebook references manually-listed cleaning dates (`log-CE`) and compares with `ra-CE` (rain-driven). Production has no `cleaning_events` table — a gap if you want to validate algorithm output against ground truth.

4. **Hampel / FBP / cleaning-event detection are notebook-only.** None of the soiling algorithms is ported to `services/intelligence/`. They run on CSV exports today.

5. **POA model mismatch.** Notebooks use ERBS + isotropic; DT uses Hay-Davies. Same site, same inputs will give different POA. Decide on a single reference model before comparing modeled-vs-measured deltas across systems.

6. **Thermal model mismatch.** Notebook Shadow Filter uses SAPM module-temp `(-3.56, -0.075)`; DT uses PVsyst `u_c = 29.0`. Both are valid; pick one per analysis context.

7. **Azimuth convention differs.** Shadow Filtering uses azimuth = 0 for due south; superpower-systems-main uses 180 for due south (pvlib default). Notebooks need a `+180` shift if reading directly from `plants.azimuth_deg`.

8. **Loss thresholds are hard-coded.** Clipping (0.85 / 0.01) and grid-loss (10 kW) thresholds live in Python source, not in `model.yaml` or `.env`. New sites cannot be tuned without code changes — surface these to config if soiling analytics needs to be tunable per site.

9. **Rainfall is hourly, soiling expects daily.** `weather_data.rainfall` is hourly; the rain-driven CE flag uses a daily 1 mm threshold. Always aggregate before applying the rule.

10. **Column-name inconsistency, GHI/DHI especially.** `solar_irradiance` (DB) vs. `Global_Horizontal_Radiation` (notebook), `diffuse_radiation` vs. `Diffuse_Horizontal_Radiation`, `temperature_2m` vs. `Weather_Temperature_Celsius`, `wind_speed` vs. `Wind_Speed`. A thin adapter (`load_weather_for_soiling(plant_id, start, end)`) that renames + resamples would eliminate these mismatches in one place.
