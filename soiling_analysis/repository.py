"""SQL access for the soiling pipeline.

Schema references and reasoning live in docs/soiling-analysis/implementation_plan.md.

The discovery query (`load_plant_topology`) is the single source of truth for
per-string config at runtime — no plant constants live in code. See ADR E-109.

Schema layout confirmed against live DB (Tiger Mumbai `dnfi6qfjjg`, 2026-05-11):
- `plant_assets.parent_id` links strings → inverter (NOT `parent_asset_id`).
- `asset_devices.model` is a top-level column (NOT in JSONB metadata).
- `asset_devices.metadata` holds inverter device specs: `ac_rating_w`,
  `eta_inv_nom`, `eta_inv_ref`, `nominal_ac_w`.
- `plant_assets.metadata` holds inverter topology: `active_string_count`,
  `modules_per_string`, `module_count`, `module_type_id`, `mppt_count`,
  `module_rate`, `cable_loss_frac`.
- Inverter `name` follows `ACB<acb>-INV<idx>` (e.g. `ACB01-INV01`).
- `module_types` schema: id, name, technology, pdc0_w, voc_v, isc_a,
  gamma_pmp, beta_voc, alpha_isc, cells_in_series.
"""
from __future__ import annotations

import logging
from datetime import date
from uuid import UUID

import pandas as pd
import psycopg2.extensions

logger = logging.getLogger(__name__)


# ----- discovery -------------------------------------------------------------

_TOPOLOGY_SQL = """
SELECT
  p.id::text                                            AS plant_id,
  p.name                                                AS plant_name,
  p.latitude,
  p.longitude,
  p.timezone,
  p.tilt_deg,
  p.azimuth_deg,
  p.albedo,
  inv.id::text                                          AS inverter_asset_id,
  inv.name                                              AS inverter_name,
  inv.electrical_id                                     AS inverter_electrical_id,
  inv_dev.model                                         AS inverter_model,
  inv_dev.make                                          AS inverter_make,
  (inv_dev.metadata->>'ac_rating_w')::float             AS inverter_ac_rating_w,
  (inv_dev.metadata->>'eta_inv_nom')::float             AS eta_inv_nom,
  (inv_dev.metadata->>'eta_inv_ref')::float             AS eta_inv_ref,
  (inv.metadata->>'active_string_count')::int           AS active_string_count,
  (inv.metadata->>'mppt_count')::int                    AS mppt_count,
  str.id::text                                          AS string_asset_id,
  (str.metadata->>'inverter_port')::int                 AS inverter_port,
  (str.metadata->>'mppt_number')::int                   AS mppt_number,
  (str.metadata->>'module_count')::int                  AS module_count,
  (str.metadata->>'port_status')                        AS port_status,
  mt.name                                               AS module_type_name,
  mt.technology                                         AS module_technology,
  mt.pdc0_w,
  mt.gamma_pmp,
  mt.beta_voc,
  mt.alpha_isc
FROM plants p
JOIN plant_assets   inv     ON inv.plant_id = p.id AND inv.asset_type = 'inverter'
LEFT JOIN asset_devices inv_dev ON inv_dev.asset_id = inv.id
JOIN plant_assets   str     ON str.plant_id = p.id
                              AND str.asset_type = 'string'
                              AND str.parent_id = inv.id
JOIN module_types   mt      ON mt.id = (str.metadata->>'module_type_id')::uuid
WHERE p.id = %s
  AND (str.metadata->>'port_status') = 'active'
ORDER BY inv.name, (str.metadata->>'inverter_port')::int;
"""


def load_plant_topology(
    conn: psycopg2.extensions.connection, plant_id: UUID
) -> pd.DataFrame:
    """Return one row per active string with everything Phase 2 needs."""
    df = pd.read_sql(_TOPOLOGY_SQL, conn, params=(str(plant_id),))
    if df.empty:
        logger.warning("Topology query returned no active strings for plant %s", plant_id)
        return df

    bad_model = df[df["inverter_model"].fillna("") != "WP-330KTL-H1"]
    if not bad_model.empty:
        logger.warning(
            "Found %d strings on inverters with unexpected model: %s",
            len(bad_model),
            sorted(bad_model["inverter_model"].dropna().unique().tolist()),
        )
    return df


# ----- per-string data loads -------------------------------------------------

def load_string_pr(
    conn: psycopg2.extensions.connection,
    string_asset_id: UUID,
    start: date,
    end: date,
) -> pd.Series:
    """Return daily ``pr_corrected`` for one string as a Series indexed by date."""
    df = pd.read_sql(
        """
        SELECT date, pr_corrected
        FROM daily_string_pr
        WHERE string_asset_id = %s AND date >= %s AND date <= %s
        ORDER BY date;
        """,
        conn,
        params=(str(string_asset_id), start, end),
    )
    if df.empty:
        return pd.Series(dtype=float, name="pr_corrected")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["pr_corrected"].astype(float)


def load_rainfall_daily(
    conn: psycopg2.extensions.connection,
    plant_id: UUID,
    start: date,
    end: date,
) -> pd.Series:
    """Return daily total rainfall (mm) for the plant, summed from hourly rows."""
    df = pd.read_sql(
        """
        SELECT timestamp::date AS date, SUM(COALESCE(rainfall, 0)) AS rainfall_mm
        FROM weather_data
        WHERE plant_id = %s AND timestamp::date >= %s AND timestamp::date <= %s
        GROUP BY 1
        ORDER BY 1;
        """,
        conn,
        params=(str(plant_id), start, end),
    )
    if df.empty:
        return pd.Series(dtype=float, name="rainfall_mm")
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["rainfall_mm"].astype(float)


def load_logged_cleanings(
    conn: psycopg2.extensions.connection,
    asset_id: UUID,
    start: date,
    end: date,
) -> list[date]:
    """Return O&M-logged cleaning dates for one string asset."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT date FROM cleaning_events
        WHERE asset_id = %s AND source IN ('logged','both')
              AND date >= %s AND date <= %s
        ORDER BY date;
        """,
        (str(asset_id), start, end),
    )
    return [row[0] for row in cur.fetchall()]


# ----- writes ----------------------------------------------------------------

def refresh_daily_string_pr(conn: psycopg2.extensions.connection) -> None:
    """Refresh the `daily_string_pr` matview before the run starts.

    CONCURRENTLY requires the unique index defined in migration 036.
    """
    cur = conn.cursor()
    cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY daily_string_pr;")


def write_cleaning_events(
    conn: psycopg2.extensions.connection,
    plant_id: UUID,
    rows: pd.DataFrame,
) -> int:
    """Upsert (asset_id, date, source)-idempotent rows into `cleaning_events`.

    Expected columns: ``asset_id`` (UUID or None), ``date``, ``source``,
    ``confidence``, ``notes``.
    """
    if rows.empty:
        return 0
    cur = conn.cursor()
    sql = """
        INSERT INTO cleaning_events (plant_id, asset_id, date, source, confidence, notes)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (asset_id, date, source) DO UPDATE
          SET confidence = EXCLUDED.confidence,
              notes      = COALESCE(EXCLUDED.notes, cleaning_events.notes),
              detected_at = now();
    """
    payload = [
        (
            str(plant_id),
            str(r["asset_id"]) if pd.notna(r.get("asset_id")) else None,
            r["date"],
            r["source"],
            float(r["confidence"]) if pd.notna(r.get("confidence")) else None,
            r.get("notes"),
        )
        for _, r in rows.iterrows()
    ]
    cur.executemany(sql, payload)
    return len(payload)


def write_string_soiling(
    conn: psycopg2.extensions.connection,
    rows: pd.DataFrame,
) -> int:
    """Upsert (asset_id, date) rows into `daily_string_soiling`."""
    if rows.empty:
        return 0
    cur = conn.cursor()
    sql = """
        INSERT INTO daily_string_soiling
          (asset_id, date, pr_corrected, pr_filtered, segment_id,
           segment_length_days, soiling_rate_pct_per_day)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (asset_id, date) DO UPDATE
          SET pr_corrected             = EXCLUDED.pr_corrected,
              pr_filtered              = EXCLUDED.pr_filtered,
              segment_id               = EXCLUDED.segment_id,
              segment_length_days      = EXCLUDED.segment_length_days,
              soiling_rate_pct_per_day = EXCLUDED.soiling_rate_pct_per_day,
              computed_at              = now();
    """
    payload = [
        (
            str(r["asset_id"]),
            r["date"],
            r.get("pr_corrected"),
            r.get("pr_filtered"),
            r.get("segment_id"),
            r.get("segment_length_days"),
            r.get("soiling_rate_pct_per_day"),
        )
        for _, r in rows.iterrows()
    ]
    cur.executemany(sql, payload)
    return len(payload)
