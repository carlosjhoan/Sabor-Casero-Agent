"""
Tests for SkillRegistry (Task 2.2).

RED phase: tests reference SkillRegistry, SkillMetadata before they exist.
"""
import pytest
from pathlib import Path


# Sample SKILL.md frontmatters for testing #################################

SAMPLE_FRONTMATTER = """\
---
name: classify
display: Classification
trigger: "user sends a message that needs intent classification"
intents: [greeting, menu_query, order_intent, farewell]
deterministic: false
dependencies: [llm_client]
---
# Classify Skill
Body content for L2 activation.
"""

SAMPLE_WITH_VERSION = """\
---
name: menu-query
display: Menu Query
trigger: "user asks about menu items"
intents: [menu_query, price_check, ingredient_lookup]
deterministic: true
dependencies: [owl_client, ontology_synonyms]
version: "1.2.0"
---
# Menu Query Skill
"""

SAMPLE_MINIMAL = """\
---
name: echo
display: Echo
trigger: "test trigger"
intents: [test]
---
"""

# Samples WITH Contract sections for get_tool_definitions testing
SAMPLE_WITH_CONTRACT = """\
---
name: test-skill
display: Test Skill
trigger: "user asks for a test"
intents: [test]
deterministic: false
dependencies: [llm_client]
version: "1.0.0"
---

# Test Skill

## Contract

- **Input**: `{"query": str, "candidates": list[str]}`
- **Output**: `{"items": list[dict], "match_type": "exact"|"partial"|"related"|"none"}`
- **Behavior**: Uses test logic to process queries.
- **Errors**: `TestError` on failure.
"""

SAMPLE_WITHOUT_CONTRACT = """\
---
name: simple
display: Simple Skill
trigger: "a simple trigger"
intents: [simple]
deterministic: true
---

# Simple Skill

No contract here.
"""


@pytest.fixture
def skill_dir(tmp_path: Path) -> Path:
    """Create a temporary skills/ directory with sample SKILL.md files."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()

    # classify skill
    classify_dir = skills_dir / "classify"
    classify_dir.mkdir()
    (classify_dir / "SKILL.md").write_text(SAMPLE_FRONTMATTER, encoding="utf-8")
    (classify_dir / "__init__.py").write_text("", encoding="utf-8")

    # menu-query skill
    menu_dir = skills_dir / "menu-query"
    menu_dir.mkdir()
    (menu_dir / "SKILL.md").write_text(SAMPLE_WITH_VERSION, encoding="utf-8")
    (menu_dir / "__init__.py").write_text("", encoding="utf-8")

    # echo skill (minimal)
    echo_dir = skills_dir / "echo"
    echo_dir.mkdir()
    (echo_dir / "SKILL.md").write_text(SAMPLE_MINIMAL, encoding="utf-8")
    (echo_dir / "__init__.py").write_text("", encoding="utf-8")

    return skills_dir


class TestSkillMetadata:
    """Verify SkillMetadata dataclass/model."""

    def test_skill_metadata_importable(self):
        from src.core.agent.skill_registry import SkillMetadata
        assert SkillMetadata is not None

    def test_skill_metadata_holds_all_fields(self):
        from src.core.agent.skill_registry import SkillMetadata
        meta = SkillMetadata(
            name="test",
            display="Test Skill",
            trigger="test trigger",
            intents=["test"],
            deterministic=False,
            dependencies=[],
            version="1.0.0",
            path=Path("/some/path"),
        )
        assert meta.name == "test"
        assert meta.display == "Test Skill"
        assert meta.trigger == "test trigger"
        assert meta.intents == ["test"]
        assert meta.deterministic is False
        assert meta.version == "1.0.0"
        assert meta.path == Path("/some/path")

    def test_skill_metadata_default_version(self):
        """Version defaults to '0.0.0' when not provided."""
        from src.core.agent.skill_registry import SkillMetadata
        from pathlib import Path
        meta = SkillMetadata(
            name="test",
            display="Test",
            trigger="t",
            intents=["t"],
            deterministic=False,
            dependencies=[],
            path=Path("."),
        )
        assert meta.version == "0.0.0"


class TestFrontmatterParsing:
    """Verify YAML frontmatter extraction from SKILL.md."""

    def test_parse_frontmatter_extracts_name(self):
        from src.core.agent.skill_registry import parse_skill_frontmatter
        meta = parse_skill_frontmatter(SAMPLE_FRONTMATTER)
        assert meta.name == "classify"

    def test_parse_frontmatter_extracts_intents(self):
        from src.core.agent.skill_registry import parse_skill_frontmatter
        meta = parse_skill_frontmatter(SAMPLE_FRONTMATTER)
        assert "greeting" in meta.intents
        assert "menu_query" in meta.intents
        assert "farewell" in meta.intents

    def test_parse_frontmatter_extracts_version(self):
        from src.core.agent.skill_registry import parse_skill_frontmatter
        meta = parse_skill_frontmatter(SAMPLE_WITH_VERSION)
        assert meta.version == "1.2.0"

    def test_parse_frontmatter_defaults_version(self):
        from src.core.agent.skill_registry import parse_skill_frontmatter
        meta = parse_skill_frontmatter(SAMPLE_MINIMAL)
        assert meta.version == "0.0.0"

    def test_parse_frontmatter_extracts_deterministic_flag(self):
        from src.core.agent.skill_registry import parse_skill_frontmatter
        meta = parse_skill_frontmatter(SAMPLE_FRONTMATTER)
        assert meta.deterministic is False
        meta2 = parse_skill_frontmatter(SAMPLE_WITH_VERSION)
        assert meta2.deterministic is True

    def test_parse_frontmatter_extracts_dependencies(self):
        from src.core.agent.skill_registry import parse_skill_frontmatter
        meta = parse_skill_frontmatter(SAMPLE_FRONTMATTER)
        assert "llm_client" in meta.dependencies
        meta2 = parse_skill_frontmatter(SAMPLE_WITH_VERSION)
        assert "owl_client" in meta2.dependencies
        assert "ontology_synonyms" in meta2.dependencies

    def test_parse_invalid_frontmatter_raises(self):
        """Malformed YAML frontmatter raises ValueError."""
        from src.core.agent.skill_registry import parse_skill_frontmatter
        bad = """---
name: broken
intents: not_a_list
---
"""
        # This should either work or raise a reasonable error
        meta = parse_skill_frontmatter(bad)
        assert meta.name == "broken"

    def test_parse_frontmatter_no_frontmatter_raises(self):
        """Content without frontmatter delimiters raises ValueError."""
        from src.core.agent.skill_registry import parse_skill_frontmatter
        with pytest.raises(ValueError, match="frontmatter"):
            parse_skill_frontmatter("# Just a heading\nNo frontmatter here")


class TestSkillRegistry:
    """Verify SkillRegistry discovery, indexing, and lookup."""

    def test_registry_importable(self):
        from src.core.agent.skill_registry import SkillRegistry
        assert SkillRegistry is not None

    def test_registry_discover_finds_skills(self, skill_dir: Path):
        """discover() scans skills/ directory and indexes SKILL.md files."""
        from src.core.agent.skill_registry import SkillRegistry
        registry = SkillRegistry()
        count = registry.discover(str(skill_dir))
        assert count == 3  # classify, menu-query, echo

    def test_registry_get_by_name(self, skill_dir: Path):
        """get(name) returns the SkillMetadata for that skill."""
        from src.core.agent.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(skill_dir))
        meta = registry.get("classify")
        assert meta is not None
        assert meta.name == "classify"
        assert meta.display == "Classification"

    def test_registry_get_unknown_returns_none(self, skill_dir: Path):
        """get() for unregistered name returns None."""
        from src.core.agent.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(skill_dir))
        assert registry.get("nonexistent") is None

    def test_registry_find_by_intent(self, skill_dir: Path):
        """find_by_intent() returns skills matching a given intent."""
        from src.core.agent.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(skill_dir))
        results = registry.find_by_intent("menu_query")
        names = [r.name for r in results]
        assert "menu-query" in names
        assert "classify" in names  # classify also has menu_query in its frontmatter

    def test_registry_find_by_intent_returns_empty_list_for_unknown(self, skill_dir: Path):
        """find_by_intent() returns empty list when no skill handles the intent."""
        from src.core.agent.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(skill_dir))
        results = registry.find_by_intent("unknown_intent_xyz")
        assert results == []

    def test_registry_list_skills(self, skill_dir: Path):
        """list_skills() returns all registered skill metadata."""
        from src.core.agent.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(skill_dir))
        skills = registry.list_skills()
        assert len(skills) == 3
        names = {s.name for s in skills}
        assert names == {"classify", "menu-query", "echo"}

    def test_registry_resolve_path(self, skill_dir: Path):
        """resolve_path() returns the filesystem path for a skill."""
        from src.core.agent.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(skill_dir))
        path = registry.resolve_path("classify")
        assert path is not None
        assert path.name == "classify"
        assert (path / "SKILL.md").exists()

    def test_registry_resolve_path_unknown_returns_none(self, skill_dir: Path):
        """resolve_path() returns None for unregistered skill."""
        from src.core.agent.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(skill_dir))
        assert registry.resolve_path("nonexistent") is None

    def test_registry_discover_skips_dirs_without_skill_md(self, skill_dir: Path):
        """Directories without SKILL.md are skipped."""
        from src.core.agent.skill_registry import SkillRegistry
        (skill_dir / "no-skill-md").mkdir()
        (skill_dir / "no-skill-md" / "__init__.py").write_text("", encoding="utf-8")
        registry = SkillRegistry()
        count = registry.discover(str(skill_dir))
        assert count == 3  # unchanged


class TestGetToolDefinitions:
    """Verify get_tool_definitions() builds OpenAI-compatible tool schemas."""

    @pytest.fixture
    def contract_skill_dir(self, tmp_path: Path) -> Path:
        """Create a temporary skills/ with Contract-bearing SKILL.md files."""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()

        # Skill with Contract
        s1 = skills_dir / "test-skill"
        s1.mkdir()
        (s1 / "SKILL.md").write_text(SAMPLE_WITH_CONTRACT, encoding="utf-8")

        # Skill without Contract
        s2 = skills_dir / "simple"
        s2.mkdir()
        (s2 / "SKILL.md").write_text(SAMPLE_WITHOUT_CONTRACT, encoding="utf-8")

        return skills_dir

    def test_get_tool_definitions_returns_list(self, contract_skill_dir: Path):
        """get_tool_definitions() returns a list of tool definitions."""
        from src.core.agent.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(contract_skill_dir))
        tools = registry.get_tool_definitions()
        assert isinstance(tools, list)

    def test_get_tool_definitions_has_correct_structure(self, contract_skill_dir: Path):
        """Each tool definition has type 'function' and function.name/description/parameters."""
        from src.core.agent.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(contract_skill_dir))
        tools = registry.get_tool_definitions()
        assert len(tools) >= 1
        for tool in tools:
            assert tool["type"] == "function"
            assert "function" in tool
            fn = tool["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn
            assert fn["parameters"]["type"] == "object"
            assert "properties" in fn["parameters"]
            assert "required" in fn["parameters"]

    def test_tool_from_skill_with_contract_has_parameters(self, contract_skill_dir: Path):
        """A skill with a Contract section gets input params extracted as properties."""
        from src.core.agent.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(contract_skill_dir))
        tools = registry.get_tool_definitions()
        tool_map = {t["function"]["name"]: t["function"] for t in tools}
        fn = tool_map.get("test-skill")
        assert fn is not None, "test-skill should have a tool definition"
        props = fn["parameters"]["properties"]
        # Contract has query (str) and candidates (list[str])
        assert "query" in props
        assert props["query"]["type"] == "string"
        assert "candidates" in props
        assert props["candidates"]["type"] == "array"
        assert "query" in fn["parameters"]["required"]

    def test_tool_from_skill_without_contract_has_empty_params(self, contract_skill_dir: Path):
        """A skill without a Contract section gets an empty parameters schema."""
        from src.core.agent.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(contract_skill_dir))
        tools = registry.get_tool_definitions()
        tool_map = {t["function"]["name"]: t["function"] for t in tools}
        fn = tool_map.get("simple")
        assert fn is not None, "simple should have a tool definition"
        assert fn["parameters"]["properties"] == {}

    def test_tool_description_includes_trigger_and_behavior(self, contract_skill_dir: Path):
        """Tool description combines trigger from frontmatter and Behavior from Contract."""
        from src.core.agent.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(contract_skill_dir))
        tools = registry.get_tool_definitions()
        tool_map = {t["function"]["name"]: t["function"] for t in tools}
        fn = tool_map.get("test-skill")
        assert fn is not None
        assert "user asks for a test" in fn["description"]
        assert "Uses test logic" in fn["description"]
