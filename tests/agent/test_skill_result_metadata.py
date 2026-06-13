"""
Tests for SkillResult metadata enrichment (Task 3.3).

Verifies that SkillResult.metadata carries ``checkpoint_id``, ``trace_id``,
``duration_ms`` when populated through the helper methods.
"""
import time
import pytest


class TestSkillResultMetadata:
    """Verify SkillResult metadata carries trace/checkpoint/duration info."""

    def test_ok_accepts_metadata(self):
        """SkillResult.ok() accepts metadata dict."""
        from src.engine.stage_result import SkillResult

        result = SkillResult.ok(
            value="hello",
            skill_name="classify",
            skill_version="1.0.0",
            metadata={"trace_id": "abc-123", "checkpoint_id": "cp-1"},
        )
        assert result.metadata["trace_id"] == "abc-123"
        assert result.metadata["checkpoint_id"] == "cp-1"

    def test_fail_accepts_metadata(self):
        """SkillResult.fail() accepts metadata dict."""
        from src.engine.stage_result import SkillResult
        from src.engine.exceptions import StageExecutionError

        err = StageExecutionError("failed", stage_name="test")
        result = SkillResult.fail(
            skill_name="rag",
            skill_version="1.0.0",
            error=err,
            metadata={"trace_id": "def-456"},
        )
        assert result.metadata["trace_id"] == "def-456"

    def test_with_trace_sets_trace_id(self):
        """with_trace() adds trace_id to metadata."""
        from src.engine.stage_result import SkillResult

        result = SkillResult.ok(value="ok", skill_name="test")
        result = result.with_trace(trace_id="trace-999")
        assert result.metadata["trace_id"] == "trace-999"

    def test_with_trace_sets_duration_ms(self):
        """with_trace() adds duration_ms to metadata."""
        from src.engine.stage_result import SkillResult

        result = SkillResult.ok(value="ok", skill_name="test")
        result = result.with_trace(trace_id="trace-x", duration_ms=123.456)
        assert result.metadata["duration_ms"] == 123.456

    def test_with_trace_duration_defaults_to_zero(self):
        """with_trace() defaults duration_ms to 0 if not provided."""
        from src.engine.stage_result import SkillResult

        result = SkillResult.ok(value="ok", skill_name="test")
        result = result.with_trace(trace_id="trace-y")
        assert result.metadata["duration_ms"] == 0

    def test_with_checkpoint_sets_checkpoint_id(self):
        """with_checkpoint() adds checkpoint_id to metadata."""
        from src.engine.stage_result import SkillResult

        result = SkillResult.ok(value="ok", skill_name="test")
        result = result.with_checkpoint(checkpoint_id="cp-42")
        assert result.metadata["checkpoint_id"] == "cp-42"

    def test_with_checkpoint_and_trace_combined(self):
        """Both with_trace and with_checkpoint can be chained."""
        from src.engine.stage_result import SkillResult

        result = SkillResult.ok(value="ok", skill_name="test")
        result = result.with_trace(trace_id="t1", duration_ms=50.0).with_checkpoint(checkpoint_id="cp-7")
        assert result.metadata["trace_id"] == "t1"
        assert result.metadata["duration_ms"] == 50.0
        assert result.metadata["checkpoint_id"] == "cp-7"

    def test_metadata_in_pipeline_error(self):
        """Failed SkillResult carries metadata with error info."""
        from src.engine.stage_result import SkillResult
        from src.engine.exceptions import StageExecutionError

        err = StageExecutionError("fail", stage_name="my-stage")
        result = SkillResult.fail(
            skill_name="test",
            error=err,
            metadata={"trace_id": "abc", "error_code": "E001"},
        )
        assert not result.success
        assert result.metadata["trace_id"] == "abc"
        assert result.metadata["error_code"] == "E001"

    def test_base_skill_execute_sets_duration(self):
        """BaseSkill.execute() populates duration_ms in metadata."""
        from src.engine.trace_context import new_trace_id
        from src.engine.skill_base import BaseSkill
        from src.engine.stage_result import SkillResult

        class TestSkill(BaseSkill):
            name = "test-skill"
            version = "1.0.0"

            async def run(self, input_data):
                return SkillResult.ok(
                    value=input_data,
                    skill_name=self.name,
                    skill_version=self.version,
                )

        import asyncio

        skill = TestSkill()
        trace_id = new_trace_id()
        result = asyncio.run(skill.execute(trace_id=trace_id, input_data={"x": 1}))

        assert result.metadata["trace_id"] == trace_id
        assert "duration_ms" in result.metadata
        assert isinstance(result.metadata["duration_ms"], (int, float))
        assert result.metadata["duration_ms"] >= 0

    def test_base_skill_execute_successful_result_value(self):
        """BaseSkill.execute() returns the correct value."""
        from src.engine.trace_context import new_trace_id
        from src.engine.skill_base import BaseSkill
        from src.engine.stage_result import SkillResult

        class TestSkill(BaseSkill):
            name = "math"
            version = "1.0.0"

            async def run(self, input_data):
                return SkillResult.ok(
                    value=input_data["x"] + input_data["y"],
                    skill_name=self.name,
                    skill_version=self.version,
                )

        import asyncio

        skill = TestSkill()
        trace_id = new_trace_id()
        result = asyncio.run(skill.execute(trace_id=trace_id, input_data={"x": 10, "y": 20}))
        assert result.success
        assert result.value == 30
        assert result.metadata["trace_id"] == trace_id
        assert result.metadata["duration_ms"] >= 0
