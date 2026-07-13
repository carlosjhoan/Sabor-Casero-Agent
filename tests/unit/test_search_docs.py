"""
Unit tests for search-docs skill (Task service-search-restructure).
"""
import pytest
from unittest.mock import AsyncMock
from src.engine.stage_result import SkillResult


class TestSearchDocsSkill:
    """search-docs skill wraps _get_context with source filter."""

    @pytest.fixture
    def skill(self):
        from skills.search_docs import Skill
        return Skill()

    def test_name_and_version(self, skill):
        """Skill has correct name and version."""
        assert skill.name == "search-docs"
        assert skill.version == "0.1.0"

    def test_load_accepts_context(self, skill):
        """load() accepts orchestration context."""
        skill.load({"retriever": AsyncMock()})
        assert hasattr(skill, "_retriever")

    def test_run_returns_skill_result(self, skill):
        """run() returns a SkillResult."""
        import asyncio
        mock_retriever = AsyncMock()
        mock_retriever.get_context = AsyncMock(return_value="chunk 1\n---\nchunk 2\n---\nchunk 3")
        skill.load({"retriever": mock_retriever})
        result = asyncio.run(skill.run({"query": "horarios", "doc_name": "service_info.txt"}))
        assert isinstance(result, SkillResult)
        assert result.success
        assert result.value["chunks_found"] == 3
        assert result.skill_name == "search-docs"

    def test_unknown_doc_returns_empty(self, skill):
        """Unknown doc_name returns empty result, not error."""
        import asyncio
        mock_retriever = AsyncMock()
        mock_retriever.get_context = AsyncMock(return_value="")
        skill.load({"retriever": mock_retriever})
        result = asyncio.run(skill.run({"query": "x", "doc_name": "nonexistent.txt"}))
        assert isinstance(result, SkillResult)
        assert result.success  # Not a failure
        assert result.value["chunks_found"] == 0
        assert result.value["result"] == ""

    def test_empty_query_returns_early(self, skill):
        """Empty query returns early with chunks_found=0."""
        import asyncio
        skill.load({"retriever": AsyncMock()})
        result = asyncio.run(skill.run({"query": "", "doc_name": "test.txt"}))
        assert result.success
        assert result.value["chunks_found"] == 0

    def test_missing_doc_name_returns_early(self, skill):
        """Missing doc_name returns early."""
        import asyncio
        skill.load({"retriever": AsyncMock()})
        result = asyncio.run(skill.run({"query": "test", "doc_name": ""}))
        assert result.success
        assert result.value["chunks_found"] == 0

    def test_missing_retriever_returns_fail(self, skill):
        """Missing retriever in context returns SkillResult.fail."""
        import asyncio
        skill.load(None)
        result = asyncio.run(skill.run({"query": "test", "doc_name": "test.txt"}))
        assert not result.success

    def test_unload_cleans_up(self, skill):
        """unload() clears references."""
        skill.load({"retriever": AsyncMock()})
        skill.unload()
        assert skill._retriever is None
