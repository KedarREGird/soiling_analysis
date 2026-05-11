"""Per-segment Prophet trend fit and length-weighted aggregation.

Ports `Non-Uniform Soiling.ipynb` cells 4–14. Each segment is the daily PR slice
between two consecutive cleaning events; Prophet fits a smooth trend; the
weighted-average daily decline is the segment's soiling rate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .config import SoilingConfig


@dataclass(frozen=True)
class Segment:
    start: date
    end: date
    pr: pd.Series              # daily PR values across [start, end]


def segment_intervals(
    pr_series: pd.Series,
    ce_dates: list[date],
    cfg: SoilingConfig,
) -> list[Segment]:
    """Split ``pr_series`` into segments bounded by consecutive cleaning events.

    Segments shorter than ``cfg.min_segment_length_days`` are dropped.
    """
    if pr_series.empty:
        return []

    sorted_ce = sorted(ce_dates)
    boundaries: list[date] = [pr_series.index.min().date()]
    boundaries.extend(d for d in sorted_ce if pr_series.index.min().date() <= d <= pr_series.index.max().date())
    boundaries.append(pr_series.index.max().date())
    # Deduplicate while preserving order.
    seen: set[date] = set()
    uniq_boundaries: list[date] = []
    for b in boundaries:
        if b not in seen:
            seen.add(b)
            uniq_boundaries.append(b)

    segments: list[Segment] = []
    for start, end in zip(uniq_boundaries[:-1], uniq_boundaries[1:], strict=False):
        # End is exclusive of the cleaning-event day itself — that day belongs
        # to the next segment (jumps back to high PR).
        mask = (pr_series.index.date >= start) & (pr_series.index.date < end)
        chunk = pr_series.loc[mask]
        if len(chunk) > cfg.min_segment_length_days:
            segments.append(Segment(start=start, end=end, pr=chunk))

    return segments


def fit_segment(seg: Segment, cfg: SoilingConfig) -> np.ndarray:
    """Return the fitted Prophet trend for a segment.

    For segments shorter than ``cfg.flat_profile_threshold_days`` the trend is
    flat — returning the segment's first value — matching notebook behaviour
    (short intervals don't show a meaningful decline).
    """
    if len(seg.pr) < cfg.flat_profile_threshold_days:
        return np.full(len(seg.pr), float(seg.pr.iloc[0]))

    # Local import: Prophet pulls cmdstan/cmdstanpy and is heavy.
    from prophet import Prophet  # type: ignore[import-not-found]

    # Prophet rejects tz-aware datetimes; PR comes from a timestamptz column.
    ds = pd.to_datetime(seg.pr.index)
    if ds.tz is not None:
        ds = ds.tz_localize(None)
    df = pd.DataFrame({"ds": ds, "y": seg.pr.values}).dropna()
    if len(df) < cfg.flat_profile_threshold_days:
        return np.full(len(seg.pr), float(seg.pr.iloc[0]))

    model = Prophet(
        n_changepoints=cfg.fbp_n_changepoints,
        changepoint_range=cfg.fbp_changepoint_range,
        yearly_seasonality=cfg.fbp_seasonality,
        weekly_seasonality=cfg.fbp_seasonality,
        daily_seasonality=cfg.fbp_seasonality,
    )
    model.fit(df)
    forecast = model.predict(df[["ds"]])
    return forecast["trend"].to_numpy()


def segment_soiling_rate(trend: np.ndarray) -> float:
    """Length-weighted daily decline of a fitted trend (% / day)."""
    if len(trend) < 2:
        return 0.0
    diffs = np.diff(trend)
    # Match the notebook's rounded-and-binned approach: average daily decline.
    # Negative diff = PR fell that day. Soiling rate is reported as a positive
    # number of %-points per day.
    return float(-np.mean(diffs) * 100.0)


def aggregate_overall(
    segments: list[Segment],
    rates_pct_per_day: list[float],
    cfg: SoilingConfig,
) -> float:
    """Length-weighted mean of per-segment rates, restricted to reliable segments.

    Only segments with ``len(segment.pr) >= cfg.reliable_interval_min_days``
    contribute, matching the paper's protocol for utility-scale plants.
    """
    if not segments:
        return 0.0
    weighted_sum = 0.0
    total_days = 0
    for seg, rate in zip(segments, rates_pct_per_day, strict=True):
        days = len(seg.pr)
        if days >= cfg.reliable_interval_min_days:
            weighted_sum += rate * days
            total_days += days
    if total_days == 0:
        return 0.0
    return weighted_sum / total_days
