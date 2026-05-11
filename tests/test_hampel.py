from __future__ import annotations

import numpy as np
import pandas as pd

from soiling_analysis.hampel import hampel_filter


def _series(n: int = 60, base: float = 0.85, seed: int = 42) -> pd.Series:
    """Daily series with small Gaussian noise so MAD is non-zero. Constant
    series degenerate to MAD=0 and the Hampel filter (correctly) refuses to
    flag — matching the notebook reference behaviour."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.Series(base + rng.normal(0, 0.005, n), index=idx, name="pr")


def test_flags_injected_spikes():
    s = _series()
    baseline_10 = s.iloc[10]
    baseline_25 = s.iloc[25]
    baseline_50 = s.iloc[50]
    s.iloc[10] = 0.30
    s.iloc[25] = 0.30
    s.iloc[50] = 0.30

    out = hampel_filter(s, window_size=7, n_sigmas=1)

    assert np.isnan(out.iloc[10])
    assert np.isnan(out.iloc[25])
    assert np.isnan(out.iloc[50])
    # Untouched neighbours.
    assert out.iloc[0] == s.iloc[0]
    assert out.iloc[20] == s.iloc[20]
    assert out.iloc[40] == s.iloc[40]


def test_returns_untouched_when_shorter_than_window():
    s = _series(n=5)
    s.iloc[2] = 0.10
    out = hampel_filter(s, window_size=7, n_sigmas=1)
    pd.testing.assert_series_equal(out, s)


def test_preserves_legitimate_decline():
    # Linear decline from 0.90 to 0.80 over 30 days with small noise — Hampel
    # should not flag the decline as outliers.
    rng = np.random.default_rng(7)
    n = 30
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    s = pd.Series(np.linspace(0.90, 0.80, n) + rng.normal(0, 0.003, n), index=idx)
    out = hampel_filter(s, window_size=7, n_sigmas=1)
    # Allow at most two flagged values across the entire decline.
    assert out.isna().sum() <= 2
