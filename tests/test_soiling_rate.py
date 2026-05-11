from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from soiling_analysis.config import SoilingConfig
from soiling_analysis.soiling_rate import (
    Segment,
    aggregate_overall,
    segment_intervals,
    segment_soiling_rate,
)


def _linear_segment(n_days: int, slope_pct_per_day: float, base: float = 0.85) -> Segment:
    idx = pd.date_range("2026-01-01", periods=n_days, freq="D")
    values = base + np.linspace(0, slope_pct_per_day / 100.0 * (n_days - 1), n_days)
    return Segment(start=idx[0].date(), end=idx[-1].date(), pr=pd.Series(values, index=idx))


def test_segment_intervals_splits_on_cleaning_events():
    cfg = SoilingConfig(min_segment_length_days=2)
    idx = pd.date_range("2026-01-01", periods=20, freq="D")
    pr = pd.Series(np.linspace(0.9, 0.8, 20), index=idx)
    ce = [date(2026, 1, 6), date(2026, 1, 14)]

    segments = segment_intervals(pr, ce, cfg)
    assert len(segments) >= 2
    # Earliest segment starts at the series start.
    assert segments[0].start == idx[0].date()


def test_segment_intervals_drops_short_segments():
    cfg = SoilingConfig(min_segment_length_days=10)
    idx = pd.date_range("2026-01-01", periods=15, freq="D")
    pr = pd.Series(np.linspace(0.9, 0.8, 15), index=idx)
    # Force two short segments with a CE in the middle.
    ce = [date(2026, 1, 5)]
    segments = segment_intervals(pr, ce, cfg)
    assert all(len(seg.pr) > cfg.min_segment_length_days for seg in segments)


def test_segment_soiling_rate_recovers_linear_slope():
    # Linear decline of -0.05 %/day over 30 days. segment_soiling_rate reports
    # a positive number for decline, so the expected output is ~0.05.
    seg = _linear_segment(n_days=30, slope_pct_per_day=-0.05)
    # Trend == raw series for a perfect line; no need to actually run Prophet.
    trend = seg.pr.to_numpy()
    rate = segment_soiling_rate(trend)
    assert rate == pytest.approx(0.05, abs=1e-3)


def test_segment_soiling_rate_zero_for_flat():
    seg = _linear_segment(n_days=20, slope_pct_per_day=0.0)
    rate = segment_soiling_rate(seg.pr.to_numpy())
    assert rate == pytest.approx(0.0, abs=1e-6)


def test_aggregate_overall_length_weighted():
    cfg = SoilingConfig(reliable_interval_min_days=14)
    seg_a = _linear_segment(n_days=30, slope_pct_per_day=-0.05)
    seg_b = _linear_segment(n_days=20, slope_pct_per_day=-0.10)
    rates = [0.05, 0.10]

    overall = aggregate_overall([seg_a, seg_b], rates, cfg)
    expected = (0.05 * 30 + 0.10 * 20) / 50
    assert overall == pytest.approx(expected, abs=1e-6)


def test_aggregate_overall_excludes_short_segments():
    cfg = SoilingConfig(reliable_interval_min_days=14)
    short = _linear_segment(n_days=10, slope_pct_per_day=-0.20)
    long = _linear_segment(n_days=30, slope_pct_per_day=-0.05)
    rates = [0.20, 0.05]

    overall = aggregate_overall([short, long], rates, cfg)
    # Short segment is excluded — overall should equal long's rate exactly.
    assert overall == pytest.approx(0.05, abs=1e-6)


def test_aggregate_overall_empty_returns_zero():
    cfg = SoilingConfig()
    assert aggregate_overall([], [], cfg) == 0.0
