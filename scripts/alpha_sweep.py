"""α-sweep for Shambhavi: rainfall-proxy F1 across α ∈ {1, 2, 3, 5, 7}.

Read-only. Loads PR + rainfall once, then runs hampel + detect_cleaning_events
at each α across all 824 active strings.

Without true O&M ground truth (logged cleanings), rainfall is the best proxy
we have. A cleaning event should land within ±1 day of a rainy day for a dry
climate; the inverse (rain → no detected event) is allowed because mild
rainfall doesn't always wash off accumulated soiling.

Score per α:
- detected_count    — total events across all strings
- rain_matched      — events within ±1 day of any plant-wide rain ≥ 1 mm
- match_rate        — rain_matched / detected_count
- strings_with_ce   — number of strings that had at least one detection

Picks the α that maximises rain_matched while keeping detection volume
reasonable (median 1–4 events per active string per quarter).
"""
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg2

from soiling_analysis.cleaning_events import detect_cleaning_events
from soiling_analysis.config import SoilingConfig
from soiling_analysis.env import load_env_file, tigerdata_connect_kwargs

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_env_file(ENV_PATH)

PLANT = "b0000000-0000-0000-0000-000000000002"
ALPHAS = [1.0, 2.0, 3.0, 5.0, 7.0]
WINDOW_DAYS = 1
RAIN_THRESHOLD_MM = 1.0

conn = psycopg2.connect(**tigerdata_connect_kwargs())

# Load PR for every active string.
print("Loading PR for all active strings ...", flush=True)
pr_full = pd.read_sql(
    """SELECT string_asset_id::text AS sid, date::date AS date, pr_corrected
       FROM daily_string_pr WHERE plant_id = %s ORDER BY string_asset_id, date;""",
    conn, params=(PLANT,),
)
pr_full["date"] = pd.to_datetime(pr_full["date"])
strings = pr_full["sid"].unique()
print(f"  {len(pr_full):,} rows · {len(strings)} strings")

# Load plant-wide daily rainfall.
rain_df = pd.read_sql(
    """SELECT timestamp::date AS date, SUM(COALESCE(rainfall,0)) AS rain_mm
       FROM weather_data WHERE plant_id = %s
       GROUP BY 1 ORDER BY 1;""",
    conn, params=(PLANT,),
)
rain_df["date"] = pd.to_datetime(rain_df["date"])
rain_days = {ts.date() for ts in rain_df.loc[rain_df["rain_mm"] >= RAIN_THRESHOLD_MM, "date"]}
print(f"  Rainfall: {len(rain_days)} days ≥ {RAIN_THRESHOLD_MM} mm\n")

def matches_rain(d: date) -> bool:
    for rd in rain_days:
        if abs((d - rd).days) <= WINDOW_DAYS:
            return True
    return False

results = []
for alpha in ALPHAS:
    cfg = SoilingConfig(ce_iqr_alpha=alpha)
    n_events = 0
    n_rain = 0
    strings_with_ce = 0
    per_string_counts = []
    for sid, group in pr_full.groupby("sid"):
        pr = group.set_index("date")["pr_corrected"].astype(float)
        if len(pr) < 14:
            continue
        events = detect_cleaning_events(pr, cfg)
        if events:
            strings_with_ce += 1
        per_string_counts.append(len(events))
        for e in events:
            n_events += 1
            if matches_rain(e):
                n_rain += 1

    match_rate = n_rain / n_events if n_events else 0.0
    median_ce = pd.Series(per_string_counts).median()
    results.append({
        "alpha": alpha,
        "events": n_events,
        "rain_matched": n_rain,
        "match_rate": match_rate,
        "strings_with_ce": strings_with_ce,
        "median_ce_per_string": median_ce,
    })
    print(f"α={alpha:>4}  events={n_events:>5}  rain_matched={n_rain:>5}  "
          f"match_rate={match_rate:.3f}  strings_with_ce={strings_with_ce:>4}  "
          f"median_per_string={median_ce}", flush=True)

# Pick the α that maximises rain_matched while detection volume stays sane.
# "Sane" = median CE per string ≤ ~4 (notebook reference assumes a handful per
# quarter, not double-digits).
print("\n--- summary ---")
df = pd.DataFrame(results)
print(df.to_string(index=False))

sane = df[df["median_ce_per_string"] <= 4]
if not sane.empty:
    pick = sane.sort_values(["match_rate", "rain_matched"], ascending=[False, False]).iloc[0]
    print(f"\nRecommended α (sane volume + best rainfall match): {pick['alpha']}")
else:
    pick = df.sort_values("match_rate", ascending=False).iloc[0]
    print(f"\nNo α has median ≤ 4; falling back to best match-rate α: {pick['alpha']}")

conn.close()
