"""
Tests for BaseSkill abstract class (Task 2.1).

RED phase: tests reference BaseSkill before it exists.
"""
import pytest
from typing import Any


class TestBaseSkill:
    """Verify BaseSkill abstract class structure and lifecycle."""

    def test_baseskill_importable(self):
        """BaseSkill can be imported from agent.skill_base."""
        from src.engine.skill_base import BaseSkill
        assert BaseSkill is not None

    def test_baseskill_is_abstract_cannot_instantiate(self):
        """BaseSkill cannot be instantiated directly — missing abstract run()."""
        from src.engine.skill_base import BaseSkill
        with pytest.raises(TypeError):
            BaseSkill()

    def test_concrete_skill_can_instantiate(self):
        """A concrete subclass with run() implemented can be instantiated."""
        from src.engine.skill_base import BaseSkill
        from src.engine.stage_result import SkillResult

        class TestSkill(BaseSkill):
            name = "test_skill"
            version = "1.0.0"

            async def run(self, input_data: Any) -> SkillResult:
                return SkillResult.ok(
                    value="done", skill_name=self.name, skill_version=self.version,
                )

        skill = TestSkill()
        assert skill.name == "test_skill"
        assert skill.version == "1.0.0"

    def test_load_sets_up_context(self):
        """load() receives orchestration context and stores it."""
        from src.engine.skill_base import BaseSkill
        from src.engine.stage_result import SkillResult

        class LoadAwareSkill(BaseSkill):
            name = "load_test"
            version = "1.0.0"

            def load(self, context: Any) -> None:
                self.loaded_context = context

            async def run(self, input_data: Any) -> SkillResult:
                return SkillResult.ok(
                    value="ok", skill_name=self.name, skill_version=self.version,
                )

        skill = LoadAwareSkill()
        ctx = {"session_id": "abc", "user_id": "u1"}
        skill.load(ctx)
        assert skill.loaded_context == ctx

    def test_run_returns_skill_result_with_correct_metadata(self):
        """run() returns a SkillResult populated with skill name and version."""
        from src.engine.skill_base import BaseSkill
        from src.engine.stage_result import SkillResult
        import asyncio

        class EchoSkill(BaseSkill):
            name = "echo"
            version = "2.0.0"

            async def run(self, input_data: Any) -> SkillResult:
                return SkillResult.ok(
                    value=input_data, skill_name=self.name, skill_version=self.version,
                )

        skill = EchoSkill()
        result = asyncio.run(skill.run({"query": "hello"}))
        assert result.success is True
        assert result.value == {"query": "hello"}
        assert result.skill_name == "echo"
        assert result.skill_version == "2.0.0"

    def test_unload_cleans_resources(self):
        """unload() releases resources held by the skill."""
        from src.engine.skill_base import BaseSkill
        from src.engine.stage_result import SkillResult

        class ResourceSkill(BaseSkill):
            name = "resource_test"
            version = "1.0.0"

            def load(self, context: Any) -> None:
                self.resources = ["db_conn", "cache"]

            async def run(self, input_data: Any) -> SkillResult:
                return SkillResult.ok(
                    value="ok", skill_name=self.name, skill_version=self.version,
                )

            def unload(self) -> None:
                self.resources = []

        skill = ResourceSkill()
        skill.load({})
        assert skill.resources == ["db_conn", "cache"]
        skill.unload()
        assert skill.resources == []

    def test_version_defaults_to_zero_zero_zero_when_not_set(self):
        """Subclass without version attr gets default '0.0.0'."""
        from src.engine.skill_base import BaseSkill
        from src.engine.stage_result import SkillResult

        class NoVersionSkill(BaseSkill):
            name = "noversion"

            async def run(self, input_data: Any) -> SkillResult:
                return SkillResult.ok(
                    value="ok", skill_name=self.name, skill_version=self.version,
                )

        skill = NoVersionSkill()
        assert skill.version == "0.0.0"

    def test_skill_fail_returns_proper_failure(self):
        """A skill that fails returns SkillResult with error, not exception."""
        from src.engine.skill_base import BaseSkill
        from src.engine.stage_result import SkillResult
        from src.engine.exceptions import StageExecutionError
        import asyncio

        class FailingSkill(BaseSkill):
            name = "failer"
            version = "1.0.0"

            async def run(self, input_data: Any) -> SkillResult:
                return SkillResult.fail(
                    skill_name=self.name,
                    skill_version=self.version,
                    error=StageExecutionError("nope", stage_name=self.name),
                )

        skill = FailingSkill()
        result = asyncio.run(skill.run({}))
        assert result.success is False
        assert result.error is not None
        assert "nope" in str(result.error)
        assert result.skill_name == "failer"
