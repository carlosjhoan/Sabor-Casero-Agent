"""
BaseSkill — abstract base class for all skills in the skill-based architecture.

Provides the ``load/run/unload`` lifecycle contract and versioning from
SKILL.md YAML frontmatter. All skills MUST subclass this and implement
``run()`` at minimum.

Usage::

    class MySkill(BaseSkill):
        name = "my-skill"
        version = "1.0.0"

        async def run(self, input_data: Any) -> SkillResult:
            ...  # core logic
"""
from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.engine.stage_result import SkillResult


class BaseSkill(ABC):
    """Abstract base class for all pipeline skills.

    Lifecycle
    ---------
        1. :meth:`load` — inject orchestration context (resources, clients,
           repositories). Called once before the first ``run()``.
        2. :meth:`run` — execute the skill's core logic. Called one or more
           times per message. MUST be overridden.
        3. :meth:`unload` — release resources. Called once when the
           orchestrator decides to evict the skill.

    Attributes
    ----------
    name : str
        Skill identifier — matches the directory name and ``SKILL.md``
        ``name`` field. Subclasses MUST set this.
    version : str
        Semver string from the SKILL.md frontmatter. Defaults to ``"0.0.0"``
        when not provided.
    """

    name: str = "unnamed"
    version: str = "0.0.0"

    def load(self, context: Any) -> None:
        """Prepare the skill with orchestration context.

        Override to set up LLM clients, repository handles, etc.
        The default implementation is a no-op.

        Args:
            context: Orchestrator-supplied context dict with session info,
                     LLM clients, and shared infrastructure references.
        """
        pass

    @abstractmethod
    async def run(self, input_data: Any) -> "SkillResult":
        """Execute the skill's core logic.

        Every concrete skill MUST implement this method.

        Args:
            input_data: Typed input per the skill's contract. The type and
                        shape are skill-specific; the SKILL.md documents
                        the contract.

        Returns:
            A ``SkillResult`` with either the skill's output on success
            or a ``PipelineError`` subtype on failure.
        """
        ...

    async def execute(
        self,
        input_data: Any,
        trace_id: str = "",
    ) -> "SkillResult":
        """Run the skill with automatic timing and trace metadata.

        This is the **preferred entry point** for the orchestrator.  It
        wraps :meth:`run` with wall-clock timing and populates
        ``metadata.trace_id`` and ``metadata.duration_ms`` on the result.

        Args:
            input_data: Typed input per the skill's contract.
            trace_id:   Trace ID to attach to the result.  If empty,
                        uses the current :func:`get_trace_id()`.

        Returns:
            A ``SkillResult`` with trace metadata populated.
        """
        import time
        from src.engine.trace_context import get_trace_id as _get_tid

        tid = trace_id or _get_tid()
        start = time.perf_counter()
        try:
            result = await self.run(input_data)
        except BaseException as exc:
            # Wrap unexpected exceptions into a failed SkillResult
            from src.engine.stage_result import SkillResult as _SR
            from src.engine.exceptions import StageExecutionError
            elapsed = (time.perf_counter() - start) * 1000
            return _SR.fail(
                skill_name=self.name,
                skill_version=self.version,
                error=StageExecutionError(
                    f"Skill '{self.name}' raised {type(exc).__name__}: {exc}",
                    stage_name=self.name,
                    original_exception=exc if isinstance(exc, Exception) else None,
                ),
            ).with_trace(trace_id=tid, duration_ms=round(elapsed, 3))

        elapsed = (time.perf_counter() - start) * 1000
        return result.with_trace(
            trace_id=tid,
            duration_ms=round(elapsed, 3),
        )

    def unload(self) -> None:
        """Release resources held by the skill.

        Override to close database connections, flush caches, cancel pending
        tasks, etc. The default implementation is a no-op.
        """
        pass
