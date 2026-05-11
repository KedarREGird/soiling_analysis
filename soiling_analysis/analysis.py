"""Single-string soiling analysis orchestration for the web UI."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd
import psycopg2

from .cleaning_events import classify_source, detect_cleaning_events
from .config import SoilingConfig
from .env import load_env_file, tigerdata_connect_kwargs
from .hampel import hampel_filter
from .repository import load_logged_cleanings, load_plant_topology, load_rainfall_daily, load_string_pr
from .soiling_rate import aggregate_overall, fit_segment, segment_intervals, segment_soiling_rate


DEFAULT_PLANT_UUID = "b0000000-0000-0000-0000-000000000002"
DEFAULT_INVERTER_NAME = "ACB01-INV05"
DEFAULT_STRING_PORT = 4
DEFAULT_START_DATE = date(2026, 2, 15)
DEFAULT_END_DATE = date(2026, 5, 5)


def _clean_float(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    if np.isnan(number) or np.isinf(number):
        return None
    return number


def _series_points(series: pd.Series, value_name: str) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for ts, value in series.items():
        points.append({"date": pd.Timestamp(ts).date().isoformat(), value_name: _clean_float(value)})
    return points


def _trend_points(index: pd.Index, trend: np.ndarray) -> list[dict[str, Any]]:
    return [
        {"date": pd.Timestamp(ts).date().isoformat(), "trend": _clean_float(value)}
        for ts, value in zip(index, trend, strict=True)
    ]


def build_config(payload: dict[str, Any]) -> SoilingConfig:
    """Build a SoilingConfig from web form values, preserving defaults."""
    base = SoilingConfig()
    updates: dict[str, Any] = {}
    for field in SoilingConfig.model_fields:
        if field in payload and payload[field] not in ("", None):
            updates[field] = payload[field]
    return base.model_copy(update=updates)


def analyze_single_string(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one single-string analysis and return JSON-serializable results."""
    load_env_file()
    load_env_file(Path(__file__).resolve().parents[1] / ".env")
    load_env_file(Path.cwd().parent / ".env")

    plant_id = UUID(str(payload.get("plant_id") or DEFAULT_PLANT_UUID))
    inverter_name = str(payload.get("inverter_name") or DEFAULT_INVERTER_NAME).strip()
    string_port = int(payload.get("string_port") or DEFAULT_STRING_PORT)
    start = date.fromisoformat(str(payload.get("start_date") or DEFAULT_START_DATE.isoformat()))
    end = date.fromisoformat(str(payload.get("end_date") or DEFAULT_END_DATE.isoformat()))
    if end < start:
        raise ValueError("End date must be on or after start date.")

    cfg = build_config(payload)

    with psycopg2.connect(**tigerdata_connect_kwargs()) as conn:
        topology = load_plant_topology(conn, plant_id)
        match = topology[
            (topology["inverter_name"] == inverter_name)
            & (topology["inverter_port"].astype(int) == string_port)
        ]
        if match.empty:
            raise ValueError(
                f"No active string found for inverter {inverter_name} port {string_port}."
            )

        row = match.iloc[0]
        string_asset_id = UUID(str(row["string_asset_id"]))
        pr = load_string_pr(conn, string_asset_id, start, end)
        if pr.empty:
            raise ValueError("No daily PR rows found for the selected string/date window.")

        rainfall = load_rainfall_daily(conn, plant_id, start, end)
        logged_dates = load_logged_cleanings(conn, string_asset_id, start, end)

    filtered = hampel_filter(
        pr,
        window_size=cfg.hampel_window_size,
        n_sigmas=cfg.hampel_n_sigmas,
        k_mad=cfg.hampel_k_mad,
    ).ffill()
    ce_dates = detect_cleaning_events(pr, cfg)
    classified = classify_source(ce_dates, rainfall, logged_dates, cfg)
    segments = segment_intervals(filtered, ce_dates, cfg)

    rates: list[float] = []
    trend_segments: list[dict[str, Any]] = []
    for idx, seg in enumerate(segments, start=1):
        try:
            trend = fit_segment(seg, cfg)
            fit_status = "prophet"
        except Exception as exc:  # Prophet/cmdstan failures should not blank the UI.
            trend = np.full(len(seg.pr), float(seg.pr.iloc[0]))
            fit_status = f"flat fallback ({type(exc).__name__})"
        rate = segment_soiling_rate(trend)
        rates.append(rate)
        trend_segments.append(
            {
                "id": idx,
                "start": seg.start.isoformat(),
                "end": seg.end.isoformat(),
                "days": len(seg.pr),
                "rate_pct_per_day": _clean_float(rate),
                "reliable": len(seg.pr) >= cfg.reliable_interval_min_days,
                "fit_status": fit_status,
                "points": _trend_points(seg.pr.index, trend),
            }
        )

    overall = aggregate_overall(segments, rates, cfg)
    outlier_count = int((pr.values != filtered.values).sum())
    events = [
        {
            "date": r["date"].isoformat() if hasattr(r["date"], "isoformat") else str(r["date"]),
            "source": r["source"],
            "confidence": _clean_float(r["confidence"]),
        }
        for _, r in classified.iterrows()
    ]

    pr_values = pr.astype(float)
    return {
        "inputs": {
            "plant_id": str(plant_id),
            "inverter_name": inverter_name,
            "string_port": string_port,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
        "topology": {
            "plant_name": row.get("plant_name"),
            "string_asset_id": str(string_asset_id),
            "inverter_asset_id": row.get("inverter_asset_id"),
            "inverter_model": row.get("inverter_model"),
            "inverter_make": row.get("inverter_make"),
            "mppt_number": int(row["mppt_number"]) if pd.notna(row.get("mppt_number")) else None,
            "port_status": row.get("port_status"),
            "module_count": int(row["module_count"]) if pd.notna(row.get("module_count")) else None,
            "module_type_name": row.get("module_type_name"),
            "module_technology": row.get("module_technology"),
            "pdc0_w": _clean_float(row.get("pdc0_w")),
        },
        "summary": {
            "days_loaded": int(len(pr)),
            "pr_min": _clean_float(pr_values.min()),
            "pr_max": _clean_float(pr_values.max()),
            "pr_mean": _clean_float(pr_values.mean()),
            "hampel_outliers": outlier_count,
            "detected_cleaning_events": len(ce_dates),
            "classified_events": len(events),
            "segments": len(segments),
            "reliable_segments": sum(1 for segment in trend_segments if segment["reliable"]),
            "overall_rate_pct_per_day": _clean_float(overall),
        },
        "config": cfg.model_dump(),
        "series": {
            "pr": _series_points(pr, "pr"),
            "filtered": _series_points(filtered, "filtered"),
            "rainfall": _series_points(rainfall, "rain_mm"),
        },
        "events": events,
        "segments": trend_segments,
    }
