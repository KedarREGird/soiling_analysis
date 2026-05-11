from pydantic import BaseModel, Field


class SoilingConfig(BaseModel):
    """Tunables for the soiling pipeline. Defaults match the reference notebooks;
    per-plant overrides land in ``plants.metadata.soiling_iqr_alpha`` once F1 tuning
    is done. See ADR E-109."""

    # Hampel filter (notebooks: window 7, n_sigmas 1, k = 1.4826).
    hampel_window_size: int = 7
    hampel_n_sigmas: int = 1
    hampel_k_mad: float = 1.4826

    # Cleaning-event detection. α = 2 bootstrap for Shambhavi; tune per-plant.
    ce_rolling_median_window: int = 7
    ce_iqr_alpha: float = 2.0
    ce_rain_threshold_mm: float = 1.0

    # Segment thresholds.
    min_segment_length_days: int = 3
    flat_profile_threshold_days: int = 11
    reliable_interval_min_days: int = 14

    # Prophet — seasonality off for the ~3-month windows the soiling paper assumes.
    fbp_n_changepoints: int = 50
    fbp_changepoint_range: float = 1.0
    fbp_seasonality: bool = False

    # Ground-truth matching tolerance for F1-score harness (days).
    ground_truth_match_window_days: int = Field(default=1, ge=0)


DEFAULT_CONFIG = SoilingConfig()
