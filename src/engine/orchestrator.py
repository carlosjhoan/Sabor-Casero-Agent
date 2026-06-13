"""
SkillOrchestrator — skill lifecycle management and intent-based decision engine.

The orchestrator owns the skill registry and acts as the coordinator between
the pipeline and the skill framework. It decides which skills to activate
based on the classified intent, manages skill loading/unloading, and
provides the ``load_skill()`` meta-tool.

Usage::

    registry = SkillRegistry()
    registry.discover("skills/")
    orch = SkillOrchestrator(registry)

    # Decide which skills to activate
    skill_names = orch.decide_skills("menu_query")

    # Load and use
    skill = orch.load_skill("menu-query")
    result = await skill.run(input_data)
    orch.unload_skill("menu-query")
"""
from __future__ import annotations

from typing import Any, Optional

from src.engine.skill_base import BaseSkill
from src.engine.skill_registry import SkillRegistry


class SkillOrchestrator:
    """Lifecycle manager and intent-based decision engine for skills.

    Parameters
    ----------
    registry : SkillRegistry
        The registry of all available skills (already discovered).
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry
        # name -> loaded BaseSkill instance
        self._loaded: dict[str, BaseSkill] = {}

    @property
    def registry(self) -> SkillRegistry:
        """The underlying skill registry."""
        return self._registry

    # ------------------------------------------------------------------
    # Decision engine
    # ------------------------------------------------------------------

    def decide_skills(self, intent: str) -> list[str]:
        """Determine which skills should be activated for a given intent.

        The orchestrator queries the registry for all skills whose
        ``intents`` list includes *intent*. Results are deduplicated and
        returned as a list of skill names.

        Args:
            intent: The classified intent label (e.g. ``"menu_query"``).

        Returns:
            Ordered list of unique skill names that handle the intent.
        """
        matches = self._registry.find_by_intent(intent)
        # Preserve order while deduplicating
        seen: set[str] = set()
        result: list[str] = []
        for m in matches:
            if m.name not in seen:
                seen.add(m.name)
                result.append(m.name)
        return result

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def load_skill(self, name: str, context: Any = None) -> BaseSkill:
        """Load a skill by name and call its ``load()`` method.

        If the skill is already loaded, returns the existing instance
        without calling ``load()`` again.

        Args:
            name: Registered skill name.
            context: Orchestration context to pass to ``skill.load()``.

        Returns:
            The loaded ``BaseSkill`` instance.

        Raises:
            KeyError: If *name* is not registered in the registry.
        """
        if name in self._loaded:
            return self._loaded[name]

        meta = self._registry.get(name)
        if meta is None:
            raise KeyError(f"Skill '{name}' is not registered in the registry")

        # Dynamically import the skill module and instantiate
        skill = self._instantiate_skill(name)
        skill.load(context)
        self._loaded[name] = skill
        return skill

    def unload_skill(self, name: str) -> None:
        """Unload a skill and call its ``unload()`` method.

        Args:
            name: Registered skill name.

        Raises:
            KeyError: If the skill is not currently loaded.
        """
        if name not in self._loaded:
            raise KeyError(f"Skill '{name}' is not currently loaded")

        skill = self._loaded[name]
        skill.unload()
        del self._loaded[name]

    def is_loaded(self, name: str) -> bool:
        """Check whether a skill is currently loaded.

        Args:
            name: Registered skill name.

        Returns:
            ``True`` if the skill is loaded, ``False`` otherwise.
        """
        return name in self._loaded

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _instantiate_skill(self, name: str) -> BaseSkill:
        """Instantiate a skill class for *name*.

        Priority:
        1. Inline-registered class (via ``registry.register_inline``) —
           used during tests.
        2. ``skills/<name>/__init__.py`` module — production path.

        Args:
            name: Skill name.

        Returns:
            An instance of ``BaseSkill``.

        Raises:
            KeyError: If neither an inline class nor a module is found.
        """
        # 1. Check for inline-registered class (testing)
        skill_class = self._registry.get_skill_class(name)
        if skill_class is not None:
            return skill_class()

        # 2. Production: import from skills/<name>/__init__.py
        import importlib

        # Handle hyphens in skill names — replace with underscores for
        # Python module import (directory names with hyphens are valid
        # on the filesystem but invalid as Python module identifiers).
        module_name = name.replace("-", "_")

        try:
            module = importlib.import_module(f"skills.{module_name}")
        except ImportError as exc:
            raise KeyError(
                f"Skill '{name}' is not registered and cannot be imported "
                f"from skills.{module_name} (tried '{module_name}')"
            ) from exc

        skill_class = getattr(module, "Skill", None)
        if skill_class is None:
            raise KeyError(
                f"Module skills.{name} does not expose a 'Skill' class"
            )

        instance: BaseSkill = skill_class()
        return instance
