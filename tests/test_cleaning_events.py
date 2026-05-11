from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from soiling_analysis.cleaning_events import (
    classify_source,
    detect_cleaning_events,
)
from soiling_analysis.config import SoilingConfig


def _decline_with_cleaning(n_per_segment: int = 30, jump_day: int = 30) -> pd.Series:
    idx = pd.date_range("2026-01-01", periods=n_per_segment * 2, freq="D")
    # Linear decline 0.90 → 0.80, then step back to 0.90 and decline again.
    seg1 = np.linspace(0.90, 0.80, n_per_segment)
    seg2 = np.linspace(0.90, 0.80, n_per_segment)
    return pd.Series(np.concatenate([seg1, seg2]), index=idx)


def test_detects_step_recovery_at_alpha_2():
    cfg = SoilingConfig(ce_iqr_alpha=2.0)
    s = _decline_with_cleaning()
    events = detect_cleaning_events(s, cfg)
    assert len(events) >= 1
    # The injected step is on day index 30.
    target = s.index[30].date()
    assert any(abs((e - target).days) <= 1 for e in events)


def test_alpha_high_suppresses_detection():
    # Series with realistic noise so IQR has some baseline spread; very large α
    # must then suppress even a substantial jump.
    rng = np.random.default_rng(11)
    idx = pd.date_range("2026-01-01", periods=60, freq="D")
    seg1 = np.linspace(0.90, 0.80, 30) + rng.normal(0, 0.01, 30)
    seg2 = np.linspace(0.90, 0.80, 30) + rng.normal(0, 0.01, 30)
    s = pd.Series(np.concatenate([seg1, seg2]), index=idx)

    cfg = SoilingConfig(ce_iqr_alpha=50.0)
    events = detect_cleaning_events(s, cfg)
    assert events == []


def test_classify_source_tags_logged_and_rainfall():
    cfg = SoilingConfig(ce_rain_threshold_mm=1.0, ground_truth_match_window_days=1)
    ce_dates = [date(2026, 1, 10), date(2026, 1, 20), date(2026, 1, 30)]
    logged_dates = [date(2026, 1, 10)]  # matches algorithm date 10.
    rainfall_idx = pd.date_range("2026-01-01", periods=31, freq="D")
    rainfall = pd.Series(0.0, index=rainfall_idx)
    rainfall.loc["2026-01-20"] = 5.0  # rainy day matches algorithm date 20.

    out = classify_source(ce_dates, rainfall, logged_dates, cfg)
    by_date = {row["date"]: row["source"] for _, row in out.iterrows()}

    assert by_date[date(2026, 1, 10)] == "both"
    assert by_date[date(2026, 1, 20)] == "rainfall"
    assert by_date[date(2026, 1, 30)] == "algorithm"


def test_classify_source_logged_only_row():
    cfg = SoilingConfig()
    out = classify_source(
        ce_dates=[],
        rainfall_daily=pd.Series(dtype=float),
        logged_dates=[date(2026, 2, 1)],
        cfg=cfg,
    )
    assert len(out) == 1
    assert out.iloc[0]["source"] == "logged"
    assert pd.isna(out.iloc[0]["confidence"])
