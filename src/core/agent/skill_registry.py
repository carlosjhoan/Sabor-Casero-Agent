"""
SkillRegistry — L1 frontmatter index, path resolution, and skill discovery.

The registry scans a ``skills/`` directory for ``SKILL.md`` files, parses
their YAML frontmatter, and builds a lightweight index of
:class:`SkillMetadata` records. The orchestrator queries this index to
decide which skills to load.

Usage::

    registry = SkillRegistry()
    registry.discover("skills/")
    meta = registry.get("classify")
    skills = registry.find_by_intent("menu_query")
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Contract parsing helpers (for get_tool_definitions)
# ---------------------------------------------------------------------------

# Regex to extract the Contract section (## Contract ... until next ## or EOF)
_CONTRACT_RE = re.compile(
    r"##\s*Contract\s*\n(.*?)(?=\n##|\Z)",
    re.DOTALL,
)

# Regex to extract Input line from Contract: `- **Input**: `{"query": str, ...}``
_INPUT_LINE_RE = re.compile(
    r"-\s*\*\*Input\*\*:\s*`(.*?)`",
)

# Regex to extract Behavior line from Contract
_BEHAVIOR_LINE_RE = re.compile(
    r"-\s*\*\*Behavior\*\*:\s*(.*)",
)

# Regex to parse individual params from the JSON-like Input string
# e.g. {"query": str, "candidates": list[str]}
_PARAM_RE = re.compile(
    r'"?(\w+)"?\s*:\s*([\w\[\]]+)',
)


def _parse_contract_input_type(raw_type: str) -> dict:
    """Map a Python-style type annotation to JSON Schema.

    Args:
        raw_type: e.g. ``"str"``, ``"int"``, ``"list[str]"``, ``"dict"``.

    Returns:
        JSON Schema property dict.
    """
    raw_type = raw_type.strip()
    if raw_type == "str":
        return {"type": "string"}
    if raw_type == "int":
        return {"type": "integer"}
    if raw_type == "float":
        return {"type": "number"}
    if raw_type == "bool":
        return {"type": "boolean"}
    if raw_type == "dict":
        return {"type": "object"}
    if raw_type.startswith("list[") and raw_type.endswith("]"):
        inner = raw_type[len("list[") : -1]
        return {"type": "array", "items": _parse_contract_input_type(inner)}
    if raw_type == "...":
        return {"description": "any"}
    return {"type": "string"}  # safe fallback


def _parse_contract_input(input_line: str) -> dict:
    """Parse the Input line from a Contract section into JSON Schema properties.

    Handles formats like::

        ``{"query": str, "candidates": list[str]}``
        ``{"classification": ..., "order_state": ...}``

    Args:
        input_line: The raw Input line content (without surrounding backticks).

    Returns:
        A dict with ``"properties"`` and ``"required"`` keys suitable for
        JSON Schema ``parameters``.
    """
    properties = {}
    required = []
    for match in _PARAM_RE.finditer(input_line):
        name = match.group(1)
        raw_type = match.group(2)
        properties[name] = _parse_contract_input_type(raw_type)
        required.append(name)
    return {"properties": properties, "required": required}


def _parse_contract_behavior(behavior_line: str) -> str:
    """Extract the behavior description from a Contract section.

    Args:
        behavior_line: Raw text of the Behavior line.

    Returns:
        Cleaned behavior description text.
    """
    return behavior_line.strip()


def _extract_contract(raw_content: str) -> dict | None:
    """Extract structured info from a SKILL.md Contract section.

    Args:
        raw_content: Full text of a SKILL.md file.

    Returns:
        Dict with ``"input"`` and ``"behavior"`` keys, or ``None`` if no
        Contract section exists.
    """
    contract_match = _CONTRACT_RE.search(raw_content)
    if not contract_match:
        return None

    contract_body = contract_match.group(1)

    # Parse Input
    input_match = _INPUT_LINE_RE.search(contract_body)
    input_schema = {}
    if input_match:
        input_schema = _parse_contract_input(input_match.group(1))

    # Parse Behavior
    behavior = ""
    behavior_match = _BEHAVIOR_LINE_RE.search(contract_body)
    if behavior_match:
        behavior = _parse_contract_behavior(behavior_match.group(1))

    return {"input": input_schema, "behavior": behavior}


# ---------------------------------------------------------------------------
# SkillMetadata — L1 discovery record
# ---------------------------------------------------------------------------

@dataclass
class SkillMetadata:
    """Lightweight metadata from a skill's SKILL.md frontmatter (Level 1).

    Attributes
    ----------
    name : str
        Unique skill identifier (matches directory name).
    display : str
        Human-readable display name.
    trigger : str
        Natural-language description of when the skill activates.
    intents : list[str]
        Intent labels this skill can handle.
    deterministic : bool
        Whether the skill produces deterministic output (no LLM).
    dependencies : list[str]
        Infrastructure dependencies (LLM client, repository, etc.).
    version : str
        Semver from frontmatter; defaults to ``"0.0.0"``.
    path : Path
        Absolute filesystem path to the skill directory.
    """

    name: str
    display: str
    trigger: str
    intents: list[str]
    deterministic: bool
    dependencies: list[str] = field(default_factory=list)
    version: str = "0.0.0"
    path: Path = Path(".")


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_skill_frontmatter(content: str) -> SkillMetadata:
    """Parse YAML frontmatter from a SKILL.md string.

    Args:
        content: Full text of a SKILL.md file.

    Returns:
        A ``SkillMetadata`` instance populated from the frontmatter.

    Raises:
        ValueError: If no ``--- ... ---`` frontmatter block is found.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        raise ValueError(
            "No YAML frontmatter found — SKILL.md must start with '---'"
        )

    raw = yaml.safe_load(match.group(1))
    if not isinstance(raw, dict):
        raise ValueError("Frontmatter is not a valid YAML mapping")

    return SkillMetadata(
        name=raw.get("name", "unnamed"),
        display=raw.get("display", raw.get("name", "unnamed")),
        trigger=raw.get("trigger", ""),
        intents=raw.get("intents", []),
        deterministic=raw.get("deterministic", False),
        dependencies=raw.get("dependencies", []),
        version=raw.get("version", "0.0.0"),
    )


# ---------------------------------------------------------------------------
# SkillRegistry
# ---------------------------------------------------------------------------

class SkillRegistry:
    """Index of available skills built from SKILL.md frontmatter.

    The registry is intentionally **read-only after discovery** — skills
    cannot be added or removed without re-scanning the filesystem (or using
    :meth:`register_inline` for tests).
    """

    def __init__(self) -> None:
        # name -> SkillMetadata
        self._skills: dict[str, SkillMetadata] = {}
        # name -> directory path
        self._paths: dict[str, Path] = {}
        # name -> raw SKILL.md content (for Contract parsing)
        self._raw_contents: dict[str, str] = {}
        # name -> skill class (for inline/test registration)
        self._skill_classes: dict[str, type] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def discover(self, skills_dir: str) -> int:
        """Scan *skills_dir* for skill subdirectories and index them.

        For each subdirectory containing a ``SKILL.md`` file, the frontmatter
        is parsed and registered. Subdirectories without ``SKILL.md`` are
        silently skipped.

        Args:
            skills_dir: Path to the root skills/ directory.

        Returns:
            Number of skills successfully registered.
        """
        base = Path(skills_dir).resolve(strict=False)
        if not base.is_dir():
            return 0

        count = 0
        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue
            skill_md = entry / "SKILL.md"
            if not skill_md.is_file():
                continue

            try:
                content = skill_md.read_text(encoding="utf-8")
                meta = parse_skill_frontmatter(content)
                meta.path = entry.resolve()
                self._skills[meta.name] = meta
                self._paths[meta.name] = entry.resolve()
                self._raw_contents[meta.name] = content
                count += 1
            except (ValueError, OSError, yaml.YAMLError):
                # Silently skip malformed skills during discovery
                continue

        return count

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[SkillMetadata]:
        """Look up a skill by its registered name.

        Returns:
            ``SkillMetadata`` if found, ``None`` otherwise.
        """
        return self._skills.get(name)

    def find_by_intent(self, intent: str) -> list[SkillMetadata]:
        """Return all skills whose ``intents`` field matches *intent*.

        Args:
            intent: The intent label to match (e.g. ``"menu_query"``).

        Returns:
            List of matching ``SkillMetadata`` objects (may be empty).
        """
        return [m for m in self._skills.values() if intent in m.intents]

    def list_skills(self) -> list[SkillMetadata]:
        """Return metadata for every registered skill."""
        return list(self._skills.values())

    def get_skill_class(self, name: str) -> Optional[type]:
        """Return the registered skill class for *name*, if any.

        Returns the class previously stored via :meth:`register_inline`,
        or ``None`` if the skill was filesystem-discovered.
        """
        return self._skill_classes.get(name)

    def resolve_path(self, name: str) -> Optional[Path]:
        """Resolve the filesystem path for a registered skill.

        Returns:
            Absolute ``Path`` to the skill directory, or ``None`` if
            the skill is not registered.
        """
        return self._paths.get(name)

    # ------------------------------------------------------------------
    # Tool definitions (OpenAI-compatible)
    # ------------------------------------------------------------------

    def get_tool_definitions(self) -> list[dict]:
        """Build OpenAI-compatible tool definitions from all discovered skills.

        For each skill, reads its SKILL.md frontmatter (name, trigger) and
        Contract section (Input, Behavior) to produce a tool definition with
        JSON Schema parameters.

        Returns:
            A list of tool definition dicts in OpenAI ``"type": "function"``
            format, suitable for passing to ``tools=`` in chat completion
            calls.

        Example return entry::

            {
                "type": "function",
                "function": {
                    "name": "classify",
                    "description": "Always — every user message...",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "message": {"type": "string"},
                            ...
                        },
                        "required": [...]
                    }
                }
            }
        """
        tools: list[dict] = []
        for name, meta in self._skills.items():
            description = meta.trigger
            contract_params = {"properties": {}, "required": []}

            # Attempt to enrich description and params from Contract section
            raw = self._raw_contents.get(name)
            if raw is not None:
                contract = _extract_contract(raw)
                if contract is not None:
                    # Append behavior to description
                    if contract["behavior"]:
                        description = f"{description} {contract['behavior']}"
                    contract_params = contract["input"]

            fn = {
                "name": meta.name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": contract_params["properties"],
                    "required": contract_params.get("required", []),
                },
            }
            tools.append({"type": "function", "function": fn})
        return tools

    # ------------------------------------------------------------------
    # Test helper
    # ------------------------------------------------------------------

    def register_inline(
        self,
        name: str,
        metadata: dict,
        skill_class: type = None,
    ) -> None:
        """Register a skill programmatically (for testing).

        Args:
            name: Skill identifier.
            metadata: Dict of frontmatter fields.
            skill_class: Optional ``BaseSkill`` subclass to associate with
                this skill name. When provided, the orchestrator can
                instantiate it directly without importing from ``skills/``.
        """
        meta = SkillMetadata(
            name=metadata.get("name", name),
            display=metadata.get("display", name),
            trigger=metadata.get("trigger", ""),
            intents=metadata.get("intents", []),
            deterministic=metadata.get("deterministic", False),
            dependencies=metadata.get("dependencies", []),
            version=metadata.get("version", "0.0.0"),
            path=Path("."),
        )
        self._skills[name] = meta
        self._paths[name] = Path(".")
        if skill_class is not None:
            self._skill_classes[name] = skill_class
