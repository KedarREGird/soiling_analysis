"""Hampel filter — replace per-day PR outliers with NaN.

Single source of truth for both `cleaning_events.detect_cleaning_events` and the
diagnostic plot path. Ports the implementation from `Hampel Filter
implementation.ipynb` / `Non-Uniform Soiling.ipynb` (which duplicated it).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def hampel_filter(
    series: pd.Series,
    window_size: int = 7,
    n_sigmas: int = 1,
    k_mad: float = 1.4826,
) -> pd.Series:
    """Return a copy of ``series`` with Hampel-detected outliers replaced by NaN.

    Symmetric sliding window of ``window_size`` (centre value included). At each
    position, MAD is scaled by ``k_mad`` (1.4826 for Gaussian) to estimate σ; a
    point is flagged if its deviation from the window median exceeds
    ``n_sigmas × σ``.

    Series shorter than ``window_size`` is returned untouched.
    """
    if len(series) < window_size:
        return series.copy()

    half = window_size // 2
    values = series.to_numpy(dtype=float, copy=True)
    out = values.copy()

    for i in range(half, len(values) - half):
        window = values[i - half : i + half + 1]
        x0 = np.nanmedian(window)
        s0 = k_mad * np.nanmedian(np.abs(window - x0))
        if s0 > 0 and abs(values[i] - x0) > n_sigmas * s0:
            out[i] = np.nan

    return pd.Series(out, index=series.index, name=series.name)
