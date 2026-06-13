"""
Tests for SkillOrchestrator (Task 2.3).

RED phase: tests reference SkillOrchestrator before it exists.
"""
import pytest
from typing import Any
from pathlib import Path


SAMPLE_FRONTMATTER_MULTI = """\
---
name: classify
display: Classification
trigger: "user sends a message"
intents: [greeting, menu_query, order_intent, farewell, info_request]
deterministic: false
dependencies: [llm_client]
---
# Classify
"""

SAMPLE_MENU_FRONTMATTER = """\
---
name: menu-query
display: Menu Query
trigger: "user asks about menu"
intents: [menu_query, price_check, ingredient_lookup]
deterministic: true
dependencies: [owl_client]
---
# Menu Query
"""

SAMPLE_ORDER_FRONTMATTER = """\
---
name: order-flow
display: Order Flow
trigger: "user wants to order"
intents: [order_intent, confirmation, cancellation]
deterministic: false
dependencies: [order_orchestrator]
---
# Order Flow
"""


@pytest.fixture
def skill_dir_with_skills(tmp_path: Path) -> Path:
    """Create a temp skills/ dir with classify, menu-query, order-flow."""
    base = tmp_path / "skills"
    for name, fm in [
        ("classify", SAMPLE_FRONTMATTER_MULTI),
        ("menu-query", SAMPLE_MENU_FRONTMATTER),
        ("order-flow", SAMPLE_ORDER_FRONTMATTER),
    ]:
        d = base / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(fm, encoding="utf-8")
        (d / "__init__.py").write_text("", encoding="utf-8")
    return base


class TestSkillOrchestrator:
    """Verify SkillOrchestrator lifecycle and decision engine."""

    def test_orchestrator_importable(self):
        from src.engine.orchestrator import SkillOrchestrator
        assert SkillOrchestrator is not None

    def test_orchestrator_initialized_with_registry(self):
        from src.engine.orchestrator import SkillOrchestrator
        from src.engine.skill_registry import SkillRegistry
        registry = SkillRegistry()
        orch = SkillOrchestrator(registry)
        assert orch.registry is registry

    def test_decide_skills_returns_relevant_skills(self, skill_dir_with_skills: Path):
        """decide_skills('menu_query') returns menu-query and classify."""
        from src.engine.orchestrator import SkillOrchestrator
        from src.engine.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(skill_dir_with_skills))
        orch = SkillOrchestrator(registry)
        skills = orch.decide_skills("menu_query")
        assert "menu-query" in skills
        assert "classify" in skills  # classify also handles menu_query

    def test_decide_skills_returns_classify_for_greeting(self, skill_dir_with_skills: Path):
        """decide_skills('greeting') returns classify (only match)."""
        from src.engine.orchestrator import SkillOrchestrator
        from src.engine.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(skill_dir_with_skills))
        orch = SkillOrchestrator(registry)
        skills = orch.decide_skills("greeting")
        assert "classify" in skills
        assert len(skills) == 1

    def test_decide_skills_returns_empty_for_unknown_intent(self, skill_dir_with_skills: Path):
        """decide_skills for unknown intent returns empty list."""
        from src.engine.orchestrator import SkillOrchestrator
        from src.engine.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(skill_dir_with_skills))
        orch = SkillOrchestrator(registry)
        skills = orch.decide_skills("unknown_intent_xyz")
        assert skills == []

    def test_load_skill_loads_and_calls_load(self, skill_dir_with_skills: Path):
        """load_skill() instantiates the skill class and calls load()."""
        from src.engine.orchestrator import SkillOrchestrator
        from src.engine.skill_registry import SkillRegistry
        from src.engine.skill_base import BaseSkill
        from src.engine.stage_result import SkillResult

        # Register a mock skill module
        registry = SkillRegistry()
        registry.register_inline(
            name="echo",
            metadata={
                "name": "echo",
                "display": "Echo",
                "trigger": "test",
                "intents": ["test"],
                "deterministic": True,
                "dependencies": [],
            },
            skill_class=type(
                "EchoSkill",
                (BaseSkill,),
                {
                    "name": "echo",
                    "version": "1.0.0",
                    "load": lambda self, ctx: setattr(self, "loaded", True),
                    "run": lambda self, inp: SkillResult.ok(
                        value=inp, skill_name=self.name, skill_version=self.version,
                    ),
                    "unload": lambda self: setattr(self, "loaded", False),
                },
            ),
        )
        orch = SkillOrchestrator(registry)
        skill = orch.load_skill("echo")
        assert skill is not None
        assert skill.loaded is True

    def test_unload_skill_calls_unload(self, skill_dir_with_skills: Path):
        """unload_skill() calls unload() on the loaded skill."""
        from src.engine.orchestrator import SkillOrchestrator
        from src.engine.skill_registry import SkillRegistry
        from src.engine.skill_base import BaseSkill
        from src.engine.stage_result import SkillResult

        registry = SkillRegistry()
        registry.register_inline(
            name="echo",
            metadata={"name": "echo", "display": "Echo", "trigger": "t", "intents": ["t"], "deterministic": True, "dependencies": []},
            skill_class=type(
                "EchoSkill",
                (BaseSkill,),
                {
                    "name": "echo",
                    "version": "1.0.0",
                    "load": lambda self, ctx: setattr(self, "loaded", True),
                    "run": lambda self, inp: SkillResult.ok(value=inp, skill_name=self.name, skill_version=self.version),
                    "unload": lambda self: setattr(self, "loaded", False),
                },
            ),
        )
        orch = SkillOrchestrator(registry)
        skill = orch.load_skill("echo")
        assert skill.loaded is True
        orch.unload_skill("echo")
        assert skill.loaded is False

    def test_load_skill_raises_for_unknown(self, skill_dir_with_skills: Path):
        """load_skill for unregistered skill raises KeyError."""
        from src.engine.orchestrator import SkillOrchestrator
        from src.engine.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(skill_dir_with_skills))
        orch = SkillOrchestrator(registry)
        with pytest.raises(KeyError, match="unknown_skill"):
            orch.load_skill("unknown_skill")

    def test_is_loaded_checks_loaded_state(self, skill_dir_with_skills: Path):
        """is_loaded() reflects whether a skill is currently loaded."""
        from src.engine.orchestrator import SkillOrchestrator
        from src.engine.skill_registry import SkillRegistry
        from src.engine.skill_base import BaseSkill
        from src.engine.stage_result import SkillResult

        registry = SkillRegistry()
        registry.register_inline(
            name="echo",
            metadata={"name": "echo", "display": "Echo", "trigger": "t", "intents": ["t"], "deterministic": True, "dependencies": []},
            skill_class=type(
                "EchoSkill",
                (BaseSkill,),
                {
                    "name": "echo",
                    "version": "1.0.0",
                    "load": lambda self, ctx: setattr(self, "loaded", True),
                    "run": lambda self, inp: SkillResult.ok(value=inp, skill_name=self.name, skill_version=self.version),
                    "unload": lambda self: setattr(self, "loaded", False),
                },
            ),
        )
        orch = SkillOrchestrator(registry)
        assert orch.is_loaded("echo") is False
        orch.load_skill("echo")
        assert orch.is_loaded("echo") is True
        orch.unload_skill("echo")
        assert orch.is_loaded("echo") is False

    def test_decide_skills_deduplicates(self, skill_dir_with_skills: Path):
        """decide_skills() returns unique skill names (no duplicates)."""
        from src.engine.orchestrator import SkillOrchestrator
        from src.engine.skill_registry import SkillRegistry
        registry = SkillRegistry()
        registry.discover(str(skill_dir_with_skills))
        orch = SkillOrchestrator(registry)
        skills = orch.decide_skills("order_intent")
        # order_intent matches both classify and order-flow
        assert "classify" in skills
        assert "order-flow" in skills
        assert len(skills) == len(set(skills))  # no duplicates
