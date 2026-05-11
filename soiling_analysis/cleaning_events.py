"""Cleaning-event detection and source classification.

Algorithm follows the modified-SRR rule from the paper *A data-driven approach
to automate cleaning event detection in PV systems*: rolling median of the
Hampel-filtered PR, day-to-day diff, IQR rule ``Q3 + α·IQR``. The α scaling is
the per-plant tunable; bootstrap value is set in `config.SoilingConfig`.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from .config import SoilingConfig
from .hampel import hampel_filter


def detect_cleaning_events(pr_series: pd.Series, cfg: SoilingConfig) -> list[date]:
    """Return dates where day-to-day PR jump exceeds ``Q3 + α·IQR``.

    ``pr_series`` is expected to be daily-indexed (DatetimeIndex). Hampel filter
    is applied internally, then forward-fill, then rolling median, then IQR rule
    on the absolute day-to-day diff.
    """
    if len(pr_series) < cfg.ce_rolling_median_window + 2:
        return []

    filtered = hampel_filter(
        pr_series,
        window_size=cfg.hampel_window_size,
        n_sigmas=cfg.hampel_n_sigmas,
        k_mad=cfg.hampel_k_mad,
    ).ffill()

    smoothed = filtered.rolling(cfg.ce_rolling_median_window, center=True).median()
    diff = smoothed.diff()

    abs_diff = diff.abs().dropna()
    if len(abs_diff) < 4:
        return []

    q1 = abs_diff.quantile(0.25)
    q3 = abs_diff.quantile(0.75)
    iqr = q3 - q1
    threshold = q3 + cfg.ce_iqr_alpha * iqr

    # Cleaning events are positive jumps (PR recovers).
    flagged = diff[(diff > threshold) & diff.notna()]
    return [ts.date() for ts in flagged.index]


def classify_source(
    ce_dates: list[date],
    rainfall_daily: pd.Series,
    logged_dates: list[date],
    cfg: SoilingConfig,
) -> pd.DataFrame:
    """Tag each detected/logged date with its source.

    Sources:
      - ``logged``    — date in O&M-supplied list, not in algorithm output.
      - ``algorithm`` — algorithm-detected, no logged or rainfall match.
      - ``rainfall``  — algorithm-detected and within ``±1`` day of a day with
                        ``rainfall.resample('D').sum() ≥ cfg.ce_rain_threshold_mm``.
      - ``both``      — algorithm-detected and matches a logged date.

    Returns DataFrame with columns ``date``, ``source``, ``confidence`` (NULL for
    logged-only rows, 1.0 for algorithm-confirmed rows). Idempotent on
    (asset_id, date, source) at the storage layer; this function is purely a
    classifier and emits no asset_id.
    """
    rain_days = set()
    if rainfall_daily is not None and not rainfall_daily.empty:
        rain_resampled = rainfall_daily.resample("D").sum()
        rain_days = {
            ts.date()
            for ts in rain_resampled.index
            if rain_resampled.loc[ts] >= cfg.ce_rain_threshold_mm
        }

    logged_set = set(logged_dates)
    ce_set = set(ce_dates)
    window = cfg.ground_truth_match_window_days

    rows: list[dict] = []
    for d in sorted(ce_set | logged_set):
        in_alg = d in ce_set
        in_log = any(abs((d - ld).days) <= window for ld in logged_set)
        in_rain = any(abs((d - rd).days) <= window for rd in rain_days)

        if in_alg and in_log:
            source = "both"
            confidence = 1.0
        elif in_alg and in_rain:
            source = "rainfall"
            confidence = 0.8
        elif in_alg:
            source = "algorithm"
            confidence = 0.5
        else:
            source = "logged"
            confidence = None

        rows.append({"date": d, "source": source, "confidence": confidence})

    return pd.DataFrame(rows, columns=["date", "source", "confidence"])
