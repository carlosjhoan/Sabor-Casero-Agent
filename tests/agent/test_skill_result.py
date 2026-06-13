"""
Tests for SkillResult[T] added to stage_result.py (Task 1.2).
"""
import pytest


class TestSkillResult:
    """Verify SkillResult[T] structure and behavior."""

    def test_skill_result_importable(self):
        """SkillResult can be imported from agent.stage_result."""
        from src.engine.stage_result import SkillResult
        assert SkillResult is not None

    def test_skill_result_ok_creates_success(self):
        from src.engine.stage_result import SkillResult
        result = SkillResult.ok(value="hello", skill_name="classify", skill_version="1.0.0")
        assert result.success is True
        assert result.value == "hello"
        assert result.skill_name == "classify"
        assert result.skill_version == "1.0.0"
        assert result.error is None
        assert result.metadata == {}

    def test_skill_result_fail_creates_failure(self):
        from src.engine.stage_result import SkillResult
        from src.engine.exceptions import StageExecutionError
        error = StageExecutionError("failed", stage_name="classify")
        result = SkillResult.fail(skill_name="classify", skill_version="1.0.0", error=error)
        assert result.success is False
        assert result.value is None
        assert result.skill_name == "classify"
        assert result.skill_version == "1.0.0"
        assert result.error is error

    def test_skill_result_with_metadata(self):
        from src.engine.stage_result import SkillResult
        result = SkillResult.ok(
            value=42,
            skill_name="rag",
            skill_version="2.0.0",
            metadata={"trace_id": "abc-123", "duration_ms": 150},
        )
        assert result.metadata["trace_id"] == "abc-123"
        assert result.metadata["duration_ms"] == 150

    def test_skill_result_supports_different_types(self):
        from src.engine.stage_result import SkillResult
        str_result = SkillResult.ok(value="text", skill_name="s1", skill_version="1.0")
        assert str_result.value == "text"
        int_result = SkillResult.ok(value=99, skill_name="s2", skill_version="1.0")
        assert int_result.value == 99
        dict_result = SkillResult.ok(value={"key": "val"}, skill_name="s3", skill_version="1.0")
        assert dict_result.value == {"key": "val"}

    def test_skill_result_error_is_typed(self):
        from src.engine.stage_result import SkillResult
        from src.engine.exceptions import PipelineError
        result = SkillResult.fail(
            skill_name="test",
            skill_version="1.0.0",
            error=PipelineError("something went wrong"),
        )
        assert isinstance(result.error, PipelineError)
        assert "something went wrong" in str(result.error)

    def test_stage_result_backward_compat(self):
        """StageResult still works as before (backward-compat alias)."""
        from src.engine.stage_result import StageResult
        ok_result = StageResult.ok(42)
        assert ok_result.success is True
        assert ok_result.value == 42
        fail_result = StageResult.fail("error msg")
        assert fail_result.success is False
        assert fail_result.error_message == "error msg"
