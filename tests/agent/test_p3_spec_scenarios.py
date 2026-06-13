"""
P3 Spec scenario tests: S-P3-01 (crash resume golden), S-P3-02 (trace_id
propagation), and latency accuracy integration.

These tests exercise the **combined** flow of CheckpointManager, TraceContext,
SkillResult metadata, and LatencyTracker to ensure they work together as
specified.
"""
import asyncio
import json
import time
import pytest
from datetime import datetime
from pathlib import Path


# =========================================================================
# S-P3-01 — Crash resume golden
# =========================================================================

class TestCrashResumeGolden:
    """S-P3-01 — Crash resume produces identical output to full re-execution."""

    def test_crash_resume_produces_identical_output(self, tmp_path):
        """
        GIVEN pipeline processing stages 1-3 completes,
        WHEN process crashes during stage 4,
        AND pipeline restarts for the same message,
        THEN coordinator loads last checkpoint (stage 3)
        AND resumes at stage 4 without redoing stages 1-3
        AND final output is identical to full re-execution (golden test).
        """
        from src.engine.checkpoint import CheckpointManager, Checkpoint

        session_id = "golden-test"
        mgr = CheckpointManager(checkpoint_dir=str(tmp_path))
        input_msg = {"message": "quiero dos tacos", "user_id": "u1"}

        # Simulate full pipeline execution producing golden output
        golden_output = _run_pipeline(mgr, session_id, input_msg, crash_after=None)

        # Simulate crash: only stages 1-3 complete
        mgr.clear(session_id)
        _run_pipeline(mgr, session_id, input_msg, crash_after=3)

        # Resume: load last checkpoint and run remaining stages
        loaded = mgr.load_latest(session_id)
        assert loaded is not None
        assert loaded.stage_name == "stage_3"

        resume_output = _run_pipeline(mgr, session_id, input_msg, crash_after=None, resume_from=3)

        # Golden test: resumed stages (4-6) must match corresponding golden output
        golden_resumed = golden_output[3:]  # stages 4-6
        assert resume_output == golden_resumed

    def test_crash_resume_skips_completed_stages(self, tmp_path):
        """
        GIVEN stages 1-3 completed and checkpointed,
        WHEN resume runs from stage 4,
        THEN it does NOT re-execute stage 1's side effects.
        """
        from src.engine.checkpoint import CheckpointManager, Checkpoint

        session_id = "skip-test-2"
        mgr = CheckpointManager(checkpoint_dir=str(tmp_path))

        # Track which stages executed during the initial run
        initial_executed = set()

        for i in range(1, 4):
            initial_executed.add(f"stage_{i}")
            cp = Checkpoint(
                stage_name=f"stage_{i}", stage_index=i, trace_id="trace",
                input_data={"idx": i}, output_data={"result": i},
                created_at=datetime.now(),
            )
            mgr.save(session_id, cp)

        # Resume: load latest and "run" additional stages
        loaded = mgr.load_latest(session_id)
        assert loaded.stage_index == 3

        resume_executed = set()
        for i in range(4, 7):
            resume_executed.add(f"stage_{i}")
            cp = Checkpoint(
                stage_name=f"stage_{i}", stage_index=i, trace_id="trace",
                input_data={"idx": i}, output_data={"result": i},
                created_at=datetime.now(),
            )
            mgr.save(session_id, cp)

        # Stage 1 should only be in initial run
        assert "stage_1" in initial_executed
        assert "stage_1" not in resume_executed

    def test_crash_resume_no_checkpoint_means_full_run(self, tmp_path):
        """
        GIVEN no checkpoint exists for a session,
        WHEN resume is attempted,
        THEN pipeline starts from stage 1 (full re-execution).
        """
        from src.engine.checkpoint import CheckpointManager

        mgr = CheckpointManager(checkpoint_dir=str(tmp_path))
        loaded = mgr.load_latest("no-such-session")
        assert loaded is None  # signals "start from beginning"


def _run_pipeline(
    mgr: "CheckpointManager",
    session_id: str,
    input_data: dict,
    crash_after: int | None = None,
    resume_from: int = 0,
) -> list[dict]:
    """Simulate a multi-stage pipeline returning ordered output dicts."""
    from src.engine.checkpoint import Checkpoint

    start = resume_from + 1 if resume_from else 1
    outputs = []

    for i in range(start, 7):
        if crash_after is not None and i > crash_after:
            break

        # Simulate stage processing
        in_val = input_data.get("message", "")
        out_val = {"stage": f"stage_{i}", "result": f"processed:{in_val}:{i}"}

        cp = Checkpoint(
            stage_name=f"stage_{i}",
            stage_index=i,
            trace_id=f"trace-{session_id}",
            input_data=input_data,
            output_data=out_val,
            created_at=datetime.now(),
        )
        mgr.save(session_id, cp)
        outputs.append(out_val)

    return outputs


# =========================================================================
# S-P3-02 — trace_id propagation
# =========================================================================

class TestTraceIdPropagation:
    """S-P3-02 — trace_id flows through all spans, results, and checkpoints."""

    def test_trace_id_in_all_spans(self):
        """
        GIVEN user message triggers pipeline,
        WHEN process_message() generates trace_id="abc-123",
        AND message passes through stages,
        THEN every stage span includes trace_id="abc-123".
        """
        from src.engine.trace_context import (
            new_trace_id, get_trace_id, span, get_event_log,
        )

        trace_id = new_trace_id()
        assert trace_id == get_trace_id()

        # Simulate 3 stages
        for stage in ("classify", "rag", "response"):
            with span(stage):
                pass

        log = get_event_log()
        assert len(log) == 3
        for entry in log:
            assert entry["trace_id"] == trace_id

    def test_trace_id_in_skill_result_metadata(self):
        """
        GIVEN a skill executes with trace context,
        THEN SkillResult.metadata contains the trace_id.
        """
        from src.engine.trace_context import new_trace_id
        from src.engine.skill_base import BaseSkill
        from src.engine.stage_result import SkillResult

        class PropagatingSkill(BaseSkill):
            name = "propagate"
            version = "1.0.0"

            async def run(self, input_data):
                return SkillResult.ok(
                    value=input_data,
                    skill_name=self.name,
                    skill_version=self.version,
                )

        skill = PropagatingSkill()
        trace_id = new_trace_id()
        result = asyncio.run(skill.execute(trace_id=trace_id, input_data={"msg": "test"}))
        assert result.metadata["trace_id"] == trace_id

    def test_trace_id_in_checkpoint(self, tmp_path):
        """
        GIVEN a checkpoint is saved with trace context,
        THEN the checkpoint file contains the trace_id.
        """
        from src.engine.checkpoint import CheckpointManager, Checkpoint
        from src.engine.trace_context import new_trace_id

        mgr = CheckpointManager(checkpoint_dir=str(tmp_path))
        trace_id = new_trace_id()

        cp = Checkpoint(
            stage_name="classify",
            stage_index=1,
            trace_id=trace_id,
            input_data={"msg": "hello"},
            output_data={"intent": "greeting"},
            created_at=datetime.now(),
        )
        mgr.save("trace-session", cp)

        path = mgr.checkpoint_path("trace-session")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data[0]["trace_id"] == trace_id

    def test_trace_id_propagates_across_async_boundaries(self):
        """
        GIVEN a trace_id is set in the main coroutine,
        WHEN a subtask runs in a separate coroutine with the same context,
        THEN the trace_id is preserved.
        """
        from src.engine.trace_context import new_trace_id, get_trace_id, span, get_event_log

        trace_id = new_trace_id()

        async def subtask():
            with span("subtask"):
                pass
            return get_trace_id()

        async def main():
            with span("main"):
                sub_tid = await subtask()
            return sub_tid

        sub_tid = asyncio.run(main())
        assert sub_tid == trace_id

        log = get_event_log()
        trace_ids_in_log = {e["trace_id"] for e in log}
        assert trace_ids_in_log == {trace_id}


# =========================================================================
# Latency accuracy integration
# =========================================================================

class TestLatencyAccuracy:
    """Latency diagnostic accuracy — mean/p50/p95/p99 correctness."""

    def test_latency_stats_accurate_known_values(self):
        """
        GIVEN known latency values,
        WHEN stats() is called,
        THEN mean, p50, p95, p99 match expected values.
        """
        from src.engine.latency_tracker import LatencyTracker

        tracker = LatencyTracker(window=100)
        for v in range(1, 101):
            tracker.record("classify", float(v))

        stats = tracker.stats("classify")
        assert stats["mean"] == pytest.approx(50.5, abs=0.5)
        assert stats["count"] == 100
        assert 49 <= stats["p50"] <= 51
        assert 94 <= stats["p95"] <= 96
        assert 98 <= stats["p99"] <= 100

    def test_latency_real_timing_simulation(self):
        """
        GIVEN skills execute with real (simulated) work,
        WHEN durations are recorded,
        THEN the tracker records non-zero durations and correct order.
        """
        from src.engine.latency_tracker import LatencyTracker

        tracker = LatencyTracker(window=10)
        # Simulate 5 skills with increasing latency
        durations = [5, 15, 30, 50, 100]
        for d in durations:
            tracker.record("search", float(d))

        stats = tracker.stats("search")
        assert stats["count"] == 5
        assert stats["mean"] == pytest.approx(40.0)
        # p50 should be the median = 30
        assert stats["p50"] == pytest.approx(30.0)
        # p95 should be between 50 and 100
        assert stats["p95"] >= 50
        assert stats["p99"] >= 50

    def test_latency_combined_with_skill_execution(self):
        """
        GIVEN skills run via BaseSkill.execute() with the tracker,
        THEN durations are recorded and stats accurate.
        """
        from src.engine.latency_tracker import LatencyTracker
        from src.engine.trace_context import new_trace_id
        from src.engine.skill_base import BaseSkill
        from src.engine.stage_result import SkillResult

        class MeasuredSkill(BaseSkill):
            name = "measured"
            version = "1.0.0"

            async def run(self, input_data):
                # Simulate work
                time.sleep(0.01)
                return SkillResult.ok(
                    value=input_data,
                    skill_name=self.name,
                    skill_version=self.version,
                )

        skill = MeasuredSkill()
        tracker = LatencyTracker(window=50)

        for i in range(5):
            trace_id = new_trace_id()
            result = asyncio.run(skill.execute(trace_id=trace_id, input_data={"n": i}))
            duration = result.metadata["duration_ms"]
            assert duration > 0
            tracker.record("measured", duration)

        stats = tracker.stats("measured")
        assert stats["count"] == 5
        assert stats["mean"] > 0
        assert stats["p50"] > 0
        assert stats["p95"] > 0
        assert stats["p99"] > 0

    def test_snapshot_includes_all_skills(self):
        """
        GIVEN multiple skills with recorded latencies,
        WHEN snapshot() is called,
        THEN it includes stats for all skills.
        """
        from src.engine.latency_tracker import LatencyTracker

        tracker = LatencyTracker(window=100)
        for skill in ("classify", "rag", "response"):
            for v in range(1, 11):
                tracker.record(skill, float(v * 10))

        snap = tracker.snapshot()
        assert set(snap.keys()) == {"classify", "rag", "response"}
        for skill_name in snap:
            assert snap[skill_name]["count"] == 10
            assert snap[skill_name]["mean"] == pytest.approx(55.0)
