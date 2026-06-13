"""
Tests for LatencyTracker (Task 3.4).

Verifies mean, p50, p95, p99 latency computation per skill over a
sliding window of the last N observations (default N=100).
"""
import pytest


class TestLatencyTracker:
    """Verify LatencyTracker record/diagnostics."""

    def test_record_and_mean(self):
        """record() stores a latency and mean() returns correct average."""
        from src.engine.latency_tracker import LatencyTracker

        tracker = LatencyTracker(window=100)
        tracker.record("classify", 10.0)
        tracker.record("classify", 20.0)
        tracker.record("classify", 30.0)

        stats = tracker.stats("classify")
        assert stats["mean"] == pytest.approx(20.0)

    def test_stats_all_fields(self):
        """stats() returns mean, p50, p95, p99, count."""
        from src.engine.latency_tracker import LatencyTracker

        tracker = LatencyTracker(window=100)
        # Insert a range of values
        for v in range(1, 101):
            tracker.record("rag", float(v))

        stats = tracker.stats("rag")
        assert stats["mean"] == pytest.approx(50.5)
        assert stats["p50"] == pytest.approx(50.5, abs=1)
        assert stats["p95"] >= 95
        assert stats["p99"] >= 99
        assert stats["count"] == 100

    def test_p50_p95_p99_accuracy(self):
        """p50/p95/p99 are correctly computed for known distributions."""
        from src.engine.latency_tracker import LatencyTracker
        import math

        tracker = LatencyTracker(window=100)
        # Insert 100 values: 10, 20, ..., 1000
        for i in range(1, 101):
            tracker.record("search", float(i * 10))

        stats = tracker.stats("search")
        assert stats["p50"] == pytest.approx(505, abs=10)
        assert stats["p95"] == pytest.approx(955, abs=10)
        assert stats["p99"] == pytest.approx(991, abs=10)

    def test_nonexistent_skill(self):
        """stats() for a skill with no recordings returns zeros."""
        from src.engine.latency_tracker import LatencyTracker

        tracker = LatencyTracker(window=100)
        stats = tracker.stats("nonexistent")
        assert stats["mean"] == 0.0
        assert stats["p50"] == 0.0
        assert stats["p95"] == 0.0
        assert stats["p99"] == 0.0
        assert stats["count"] == 0

    def test_window_sliding(self):
        """Only the last N records are kept (sliding window)."""
        from src.engine.latency_tracker import LatencyTracker

        tracker = LatencyTracker(window=10)
        # Insert 20 records
        for v in range(1, 21):
            tracker.record("episodic", float(v))

        stats = tracker.stats("episodic")
        assert stats["count"] == 10  # only last 10
        # Mean of 11..20 = (11+20)/2 = 15.5
        assert stats["mean"] == pytest.approx(15.5)

    def test_multiple_skills_independent(self):
        """Latencies for different skills are tracked independently."""
        from src.engine.latency_tracker import LatencyTracker

        tracker = LatencyTracker(window=100)
        tracker.record("classify", 10.0)
        tracker.record("classify", 20.0)
        tracker.record("rag", 100.0)

        classify_stats = tracker.stats("classify")
        rag_stats = tracker.stats("rag")
        assert classify_stats["mean"] == 15.0
        assert rag_stats["mean"] == 100.0

    def test_snapshot_all_skills(self):
        """snapshot() returns stats for all recorded skills."""
        from src.engine.latency_tracker import LatencyTracker

        tracker = LatencyTracker(window=50)
        tracker.record("classify", 5.0)
        tracker.record("rag", 15.0)

        snap = tracker.snapshot()
        assert "classify" in snap
        assert "rag" in snap
        assert snap["classify"]["mean"] == 5.0
        assert snap["rag"]["mean"] == 15.0

    def test_single_record(self):
        """A single record produces correct stats (p50==p95==p99==value)."""
        from src.engine.latency_tracker import LatencyTracker

        tracker = LatencyTracker(window=100)
        tracker.record("fast", 42.0)

        stats = tracker.stats("fast")
        assert stats["mean"] == 42.0
        assert stats["p50"] == 42.0
        assert stats["p95"] == 42.0
        assert stats["p99"] == 42.0
        assert stats["count"] == 1

    def test_custom_window(self):
        """Custom window size is respected."""
        from src.engine.latency_tracker import LatencyTracker

        tracker = LatencyTracker(window=5)
        for v in range(1, 11):
            tracker.record("bursty", float(v))

        stats = tracker.stats("bursty")
        assert stats["count"] == 5
        assert stats["mean"] == pytest.approx(8.0)  # 6+7+8+9+10 / 5
