"""Backfill-window heuristic.

`find_earliest_reliable_date(plant_id)` walks 30-day windows from the earliest
`string_readings.time` for the plant; returns the start of the first window
where ≥ 80 % of expected rows are present. Expected rows = ``30 × 288 × n_active_strings``
because `string_readings` is downsampled to 5-min at ingestion (ADR E-026).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from uuid import UUID

import psycopg2.extensions

logger = logging.getLogger(__name__)

EXPECTED_BUCKETS_PER_DAY = 288  # 24 × 60 / 5 minutes; see ADR E-026
WINDOW_DAYS = 30
COVERAGE_THRESHOLD = 0.80


def find_earliest_reliable_date(
    conn: psycopg2.extensions.connection,
    plant_id: UUID,
    n_active_strings: int,
) -> date | None:
    """Return the start date of the first 30-day window with ≥ 80 % coverage.

    Returns ``None`` if no such window exists in the available history. Caller
    should persist the result in ``plants.metadata.soiling_backfill_start`` so
    subsequent runs skip the scan.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT MIN(time)::date FROM string_readings WHERE plant_id = %s;",
        (str(plant_id),),
    )
    row = cur.fetchone()
    if row is None or row[0] is None:
        return None

    cursor_date: date = row[0]
    today: date = date.today()
    expected_per_window = WINDOW_DAYS * EXPECTED_BUCKETS_PER_DAY * n_active_strings

    while cursor_date + timedelta(days=WINDOW_DAYS) <= today:
        end_date = cursor_date + timedelta(days=WINDOW_DAYS)
        cur.execute(
            """
            SELECT COUNT(*) FROM string_readings
            WHERE plant_id = %s AND time >= %s AND time < %s;
            """,
            (str(plant_id), cursor_date, end_date),
        )
        actual = cur.fetchone()[0] or 0
        coverage = actual / expected_per_window if expected_per_window else 0.0
        logger.info(
            "Coverage scan %s..%s: actual=%d expected=%d coverage=%.2f",
            cursor_date, end_date, actual, expected_per_window, coverage,
        )
        if coverage >= COVERAGE_THRESHOLD:
            return cursor_date
        cursor_date += timedelta(days=WINDOW_DAYS // 3)  # step by 10 days

    return None
