"""
Tests for P5 skills: menu-query and rag-retrieve (Tasks 5.11, 5.12).
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from pathlib import Path

from src.engine.stage_result import SkillResult


class TestMenuQuerySkill:
    """menu-query skill wraps OWL signal with ontology validation."""

    @pytest.fixture
    def skill(self):
        from skills.menu_query import Skill as MenuQuerySkill
        return MenuQuerySkill()

    def test_name_and_version(self, skill):
        """Skill has correct name and version."""
        assert skill.name == "menu-query"
        assert skill.version == "0.1.0"

    def test_load_accepts_context(self, skill):
        """load() accepts orchestration context."""
        skill.load({"owl_client": MagicMock(), "owl_signal": MagicMock()})
        assert hasattr(skill, "_owl_client")

    def test_run_returns_skill_result(self, skill):
        """run() returns a SkillResult."""
        import asyncio
        skill.load({"owl_client": MagicMock(), "owl_signal": MagicMock()})
        result = asyncio.run(skill.run({"query": "pechuga", "candidates": []}))
        assert isinstance(result, SkillResult)
        assert result.skill_name == "menu-query"

    def test_unload_cleans_up(self, skill):
        """unload() clears references."""
        skill.load({"owl_client": "test"})
        skill.unload()
        assert not hasattr(skill, "_owl_client") or skill._owl_client is None


class TestRagRetrieveSkill:
    """rag-retrieve skill wraps RAG v2 pipeline."""

    @pytest.fixture
    def skill(self):
        from skills.rag_retrieve import Skill as RagRetrieveSkill
        return RagRetrieveSkill()

    def test_name_and_version(self, skill):
        """Skill has correct name and version."""
        assert skill.name == "rag-retrieve"
        assert skill.version == "0.1.0"

    def test_load_accepts_context(self, skill):
        """load() accepts orchestration context."""
        skill.load({
            "owl_client": MagicMock(),
            "owl_signal": MagicMock(),
            "memory_hub": MagicMock(),
            "retriever": MagicMock(),
        })
        assert hasattr(skill, "_owl_client")

    def test_run_returns_skill_result(self, skill):
        """run() returns a SkillResult."""
        import asyncio
        mock_owl = MagicMock()
        mock_owl.score_candidates = MagicMock(return_value={})
        mock_owl.validate_candidates = MagicMock()
        skill.load({
            "owl_client": MagicMock(),
            "owl_signal": mock_owl,
            "memory_hub": MagicMock(),
            "retriever": MagicMock(),
        })
        result = asyncio.run(skill.run({"query": "test", "candidates": []}))
        assert isinstance(result, SkillResult)
        assert result.skill_name == "rag-retrieve"

    def test_unload_cleans_up(self, skill):
        """unload() clears references."""
        skill.load({"owl_client": "test"})
        skill.unload()
        assert not hasattr(skill, "_owl_client") or skill._owl_client is None
