"""
Tests for SkillResult[T] merge behavior (Task 2.6).

RED phase: tests reference merge methods before they exist.
"""
import pytest
from typing import Any


class TestSkillResultMerge:
    """Verify SkillResult[T] merge capabilities."""

    def test_merge_combines_results(self):
        """merge() combines multiple SkillResults into one aggregated result."""
        from src.engine.stage_result import SkillResult

        r1 = SkillResult.ok(value={"menu": ["tacos"]}, skill_name="menu-query", skill_version="1.0.0")
        r2 = SkillResult.ok(value={"order": "confirmed"}, skill_name="order-flow", skill_version="1.0.0")

        merged = SkillResult.merge([r1, r2])
        assert merged.success is True
        assert merged.skill_name == "merged"
        assert merged.value["menu-query"] == {"menu": ["tacos"]}
        assert merged.value["order-flow"] == {"order": "confirmed"}

    def test_merge_with_one_failure(self):
        """merge() fails overall if any result is a failure."""
        from src.engine.stage_result import SkillResult
        from src.engine.exceptions import StageExecutionError

        r1 = SkillResult.ok(value={"menu": ["tacos"]}, skill_name="menu-query", skill_version="1.0.0")
        r2 = SkillResult.fail(
            skill_name="order-flow",
            skill_version="1.0.0",
            error=StageExecutionError("order failed", stage_name="order-flow"),
        )

        merged = SkillResult.merge([r1, r2])
        assert merged.success is False
        # Failure details should be included
        assert merged.error is not None

    def test_merge_empty_list_returns_failure(self):
        """merge() with empty list returns a failed result."""
        from src.engine.stage_result import SkillResult

        merged = SkillResult.merge([])
        assert merged.success is False
        assert "No skills" in str(merged.error or "")

    def test_merge_all_success_multiple(self):
        """merge() groups 3+ successful results."""
        from src.engine.stage_result import SkillResult

        results = [
            SkillResult.ok(value={"a": 1}, skill_name="s1", skill_version="1.0"),
            SkillResult.ok(value={"b": 2}, skill_name="s2", skill_version="1.0"),
            SkillResult.ok(value={"c": 3}, skill_name="s3", skill_version="1.0"),
        ]
        merged = SkillResult.merge(results)
        assert merged.success is True
        assert merged.value["s1"] == {"a": 1}
        assert merged.value["s2"] == {"b": 2}
        assert merged.value["s3"] == {"c": 3}
