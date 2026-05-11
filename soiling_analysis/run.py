"""CLI entrypoint for the soiling pipeline.

Usage:
    python -m soiling_analysis.run \
        --plant <plant-uuid> \
        [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]

Defaults:
- start-date: ``plants.metadata.soiling_backfill_start`` if set, else
  the result of `find_earliest_reliable_date` (which then gets persisted).
- end-date: yesterday IST (matching ADR E-067 for consistency with the
  existing data-analysis pipeline).

See ADR E-109.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pandas as pd
import psycopg2

from .cleaning_events import classify_source, detect_cleaning_events
from .config import DEFAULT_CONFIG, SoilingConfig
from .data_quality import find_earliest_reliable_date
from .env import load_env_file, tigerdata_connect_kwargs
from .hampel import hampel_filter
from .repository import (
    load_logged_cleanings,
    load_plant_topology,
    load_rainfall_daily,
    load_string_pr,
    refresh_daily_string_pr,
    write_cleaning_events,
    write_string_soiling,
)
from .soiling_rate import (
    aggregate_overall,
    fit_segment,
    segment_intervals,
    segment_soiling_rate,
)

logger = logging.getLogger(__name__)

IST_OFFSET = timedelta(hours=5, minutes=30)


def _yesterday_ist() -> date:
    now_ist = datetime.now(timezone.utc) + IST_OFFSET
    return (now_ist - timedelta(days=1)).date()


def _resolve_start_date(
    conn: psycopg2.extensions.connection,
    plant_id: UUID,
    n_active_strings: int,
    explicit: date | None,
) -> date | None:
    if explicit is not None:
        return explicit
    cur = conn.cursor()
    cur.execute(
        "SELECT metadata->>'soiling_backfill_start' FROM plants WHERE id = %s;",
        (str(plant_id),),
    )
    row = cur.fetchone()
    if row and row[0]:
        return date.fromisoformat(row[0])

    resolved = find_earliest_reliable_date(conn, plant_id, n_active_strings)
    if resolved is None:
        return None
    cur.execute(
        """
        UPDATE plants
        SET metadata = COALESCE(metadata, '{}'::jsonb)
                       || jsonb_build_object('soiling_backfill_start', %s::text)
        WHERE id = %s;
        """,
        (resolved.isoformat(), str(plant_id)),
    )
    conn.commit()
    return resolved


def _run_one_string(
    conn: psycopg2.extensions.connection,
    plant_id: UUID,
    string_asset_id: UUID,
    start: date,
    end: date,
    rainfall_daily: pd.Series,
    cfg: SoilingConfig,
) -> dict | None:
    """Run the full pipeline for one string. Returns a summary dict or None."""
    pr = load_string_pr(conn, string_asset_id, start, end)
    if pr.empty:
        return None

    filtered = hampel_filter(
        pr,
        window_size=cfg.hampel_window_size,
        n_sigmas=cfg.hampel_n_sigmas,
        k_mad=cfg.hampel_k_mad,
    ).ffill()

    ce_dates = detect_cleaning_events(pr, cfg)
    logged = load_logged_cleanings(conn, string_asset_id, start, end)
    classified = classify_source(ce_dates, rainfall_daily, logged, cfg)
    classified["asset_id"] = str(string_asset_id)
    classified["notes"] = None
    write_cleaning_events(conn, plant_id, classified)

    segments = segment_intervals(filtered, ce_dates, cfg)
    if not segments:
        return {
            "string_asset_id": str(string_asset_id),
            "n_events": len(ce_dates),
            "n_segments": 0,
            "overall_rate_pct_per_day": None,
        }

    per_segment_rates: list[float] = []
    soiling_rows: list[dict] = []
    for idx, seg in enumerate(segments, start=1):
        trend = fit_segment(seg, cfg)
        rate = segment_soiling_rate(trend)
        per_segment_rates.append(rate)
        for day_idx, ts in enumerate(seg.pr.index):
            soiling_rows.append({
                "asset_id": str(string_asset_id),
                "date": ts.date(),
                "pr_corrected": float(seg.pr.iloc[day_idx]),
                "pr_filtered": float(filtered.get(ts, seg.pr.iloc[day_idx])),
                "segment_id": idx,
                "segment_length_days": len(seg.pr),
                "soiling_rate_pct_per_day": rate,
            })

    write_string_soiling(conn, pd.DataFrame(soiling_rows))

    overall = aggregate_overall(segments, per_segment_rates, cfg)
    return {
        "string_asset_id": str(string_asset_id),
        "n_events": len(ce_dates),
        "n_segments": len(segments),
        "overall_rate_pct_per_day": overall,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the soiling pipeline for one plant.")
    parser.add_argument("--plant", required=True, type=UUID)
    parser.add_argument("--start-date", type=date.fromisoformat, default=None)
    parser.add_argument("--end-date", type=date.fromisoformat, default=None)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    load_env_file()
    conn = psycopg2.connect(**tigerdata_connect_kwargs())
    # ADR E-023: TigerData sets read-only by default; override per-session.
    conn.cursor().execute("SET default_transaction_read_only = off;")

    try:
        topology = load_plant_topology(conn, args.plant)
        if topology.empty:
            logger.error("No active strings found for plant %s", args.plant)
            return 1

        # Per-plant α override from plants.metadata.soiling_iqr_alpha
        # (populated by scripts/alpha_sweep.py once F1/rainfall data is in).
        cur = conn.cursor()
        cur.execute(
            "SELECT (metadata->>'soiling_iqr_alpha')::float FROM plants WHERE id = %s;",
            (str(args.plant),),
        )
        row = cur.fetchone()
        cfg = DEFAULT_CONFIG
        if row and row[0] is not None:
            cfg = DEFAULT_CONFIG.model_copy(update={"ce_iqr_alpha": float(row[0])})
            logger.info("Using per-plant α = %s from plants.metadata", row[0])

        n_active = len(topology)
        end = args.end_date or _yesterday_ist()
        start = _resolve_start_date(conn, args.plant, n_active, args.start_date)
        if start is None:
            logger.error("Could not resolve start date for plant %s (no reliable window)", args.plant)
            return 2

        logger.info(
            "Plant %s: running soiling pipeline over %d active strings, %s..%s",
            args.plant, n_active, start, end,
        )

        refresh_daily_string_pr(conn)
        conn.commit()

        rainfall_daily = load_rainfall_daily(conn, args.plant, start, end)

        summaries: list[dict] = []
        for string_asset_id in topology["string_asset_id"].unique():
            try:
                # ADR E-060: per-string error isolation — one bad string
                # cannot break the whole plant run.
                result = _run_one_string(
                    conn, args.plant, UUID(string_asset_id),
                    start, end, rainfall_daily, cfg,
                )
                if result is not None:
                    summaries.append(result)
                conn.commit()
            except Exception:
                conn.rollback()
                logger.exception("Failed for string %s; continuing", string_asset_id)

        # Summary line.
        rates = [s["overall_rate_pct_per_day"] for s in summaries if s["overall_rate_pct_per_day"] is not None]
        total_events = sum(s["n_events"] for s in summaries)
        logger.info(
            "Plant %s done. strings=%d total_events=%d mean_rate=%s worst_rate=%s",
            args.plant,
            len(summaries),
            total_events,
            f"{sum(rates) / len(rates):.4f}" if rates else "n/a",
            f"{max(rates):.4f}" if rates else "n/a",
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
