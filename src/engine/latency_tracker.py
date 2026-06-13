"""
LatencyTracker — per-skill latency diagnostics.

Tracks execution durations per skill over a sliding window (default N=100)
and computes mean, p50, p95, p99.

Usage::

    tracker = LatencyTracker()
    tracker.record("classify", 123.4)
    stats = tracker.stats("classify")  # {"mean": ..., "p50": ..., ...}
    snapshot = tracker.snapshot()       # {"classify": {...}, "rag": {...}}
"""
from __future__ import annotations

import math
from collections import deque
from typing import Dict, List


class LatencyTracker:
    """Sliding-window latency tracker per skill.

    Parameters
    ----------
    window : int
        Maximum number of observations to retain per skill (default ``100``).
    """

    def __init__(self, window: int = 100) -> None:
        self._window = window
        # skill_name -> deque of duration_ms values
        self._data: Dict[str, deque] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, skill_name: str, duration_ms: float) -> None:
        """Record a single latency observation for a skill.

        Args:
            skill_name: Name of the skill.
            duration_ms: Wall-clock duration in milliseconds.
        """
        if skill_name not in self._data:
            self._data[skill_name] = deque(maxlen=self._window)
        self._data[skill_name].append(duration_ms)

    def stats(self, skill_name: str) -> dict:
        """Return latency statistics for a skill.

        Returns a dict with keys: ``mean``, ``p50``, ``p95``, ``p99``,
        ``count``.  All percentiles are 0.0 and ``count`` is 0 when
        the skill has no recorded observations.

        Args:
            skill_name: Name of the skill.
        """
        values = self._data.get(skill_name)
        if not values:
            return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "count": 0}

        sorted_vals = sorted(values)
        n = len(sorted_vals)
        return {
            "mean": sum(sorted_vals) / n,
            "p50": _percentile(sorted_vals, 50),
            "p95": _percentile(sorted_vals, 95),
            "p99": _percentile(sorted_vals, 99),
            "count": n,
        }

    def snapshot(self) -> Dict[str, dict]:
        """Return latency stats for all recorded skills.

        Returns:
            Dict mapping ``skill_name → stats dict`` (same keys as
            :meth:`stats`).
        """
        return {name: self.stats(name) for name in self._data}


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _percentile(sorted_data: List[float], percentile: float) -> float:
    """Compute the *percentile* of a sorted list.

    Uses linear interpolation (same approach as numpy's default).

    Args:
        sorted_data: Sorted list of values.
        percentile: Desired percentile (0–100).

    Returns:
        The interpolated percentile value.
    """
    if not sorted_data:
        return 0.0
    if len(sorted_data) == 1:
        return sorted_data[0]

    k = (percentile / 100.0) * (len(sorted_data) - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return d0 + d1
