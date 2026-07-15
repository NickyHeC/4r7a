"""Ephemeral specialist execute duration — soft work-ahead estimates.

Persistent managers are not timed; only specialist ``BaseAgent.execute()``
wall-clock (when ``track_duration`` is True) feeds scheduling.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from company_brain.agents.gates import StateStore

logger = logging.getLogger(__name__)

DURATION_PREFIX = "llm_runtime:duration:"
DEFAULT_MAX_SAMPLES = 20
DEFAULT_MIN_SAMPLES = 5


def _key(agent: str) -> str:
    return f"{DURATION_PREFIX}{agent}"


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (len(sorted_vals) - 1) * pct
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return sorted_vals[lo]
    weight = rank - lo
    return sorted_vals[lo] * (1 - weight) + sorted_vals[hi] * weight


def record_execute_duration(
    agent: str,
    duration_ms: float,
    *,
    max_samples: int = DEFAULT_MAX_SAMPLES,
    store: StateStore | None = None,
) -> dict[str, Any]:
    """Append one execute duration sample and recompute rolling stats."""
    if duration_ms < 0:
        duration_ms = 0.0
    store = store or StateStore()
    raw = dict(store.get(_key(agent)) or {})
    samples = list(raw.get("samples_ms") or [])
    samples.append(float(duration_ms))
    if len(samples) > max_samples:
        samples = samples[-max_samples:]
    ordered = sorted(samples)
    stats = {
        "samples_ms": samples,
        "count": len(samples),
        "p50_ms": _percentile(ordered, 0.50),
        "p95_ms": _percentile(ordered, 0.95),
        "last_ms": float(duration_ms),
    }
    store.set(_key(agent), stats)
    logger.debug(
        "Execute duration agent=%s last=%.0fms p95=%.0fms n=%d",
        agent,
        duration_ms,
        stats["p95_ms"],
        stats["count"],
    )
    return stats


def duration_stats(agent: str, *, store: StateStore | None = None) -> dict[str, Any]:
    store = store or StateStore()
    raw = store.get(_key(agent)) or {}
    return {
        "count": int(raw.get("count") or 0),
        "p50_ms": float(raw.get("p50_ms") or 0),
        "p95_ms": float(raw.get("p95_ms") or 0),
        "last_ms": float(raw.get("last_ms") or 0),
        "samples_ms": list(raw.get("samples_ms") or []),
    }


def resolve_estimated_minutes(
    agent: str,
    config_fallback: int,
    *,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    store: StateStore | None = None,
) -> int:
    """Return measured p95 minutes when enough samples exist, else config fallback."""
    fallback = max(int(config_fallback), 1)
    stats = duration_stats(agent, store=store)
    if stats["count"] < min_samples:
        return fallback
    p95_minutes = int(math.ceil(stats["p95_ms"] / 60_000.0))
    return max(p95_minutes, 1)
