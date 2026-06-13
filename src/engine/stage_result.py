"""
StageResult[T] — generic result type for pipeline stage isolation.

Provides a unified way to represent success/failure for each stage
of the message processing pipeline, with combinators for chaining.

Also provides SkillResult[T] — a slightly richer result type with skill
metadata for the skill-based architecture (P2+).
"""
from dataclasses import dataclass
from typing import Generic, TypeVar, Optional, Callable, Awaitable, Any, Dict

from pydantic import BaseModel, Field

T = TypeVar("T")
U = TypeVar("U")


@dataclass
class StageResult(Generic[T]):
    """
    Generic result for a pipeline stage.

    Use classmethods to construct:
        StageResult.ok(value)     — successful stage
        StageResult.fail(message) — failed stage with error message
    """
    success: bool
    value: Optional[T] = None
    error_message: Optional[str] = None

    @classmethod
    def ok(cls, value: T) -> "StageResult[T]":
        """Create a successful result with the given value."""
        return cls(success=True, value=value)

    @classmethod
    def fail(cls, message: str = "") -> "StageResult[T]":
        """Create a failed result with an error message."""
        return cls(success=False, error_message=message)

    def unwrap(self) -> T:
        """Return the value if successful, raise ValueError otherwise."""
        if not self.success:
            raise ValueError(
                f"Called unwrap() on failed StageResult: {self.error_message}"
            )
        return self.value

    def or_else(self, default: T) -> T:
        """Return the value if successful, or a default otherwise."""
        if self.success:
            return self.value
        return default

    def map(self, fn: Callable[[T], U]) -> "StageResult[U]":
        """Apply fn to the value if successful; pass through failure."""
        if self.success:
            try:
                return StageResult.ok(fn(self.value))
            except Exception as e:
                return StageResult.fail(str(e))
        return StageResult.fail(self.error_message)

    async def map_async(self, fn: Callable[[T], Awaitable[U]]) -> "StageResult[U]":
        """Apply async fn to the value if successful; pass through failure."""
        if self.success:
            try:
                result = await fn(self.value)
                return StageResult.ok(result)
            except Exception as e:
                return StageResult.fail(str(e))
        return StageResult.fail(self.error_message)


# =========================================================================
# SkillResult — richer result type with skill metadata (P2+)
# =========================================================================

class SkillResult(BaseModel, Generic[T]):
    """
    Typed result for a skill execution in the skill-based architecture.

    Adds skill_name, skill_version, and metadata to the StageResult pattern.
    ``error`` carries a ``PipelineError`` subtype (never a bare string).

    Usage:
        SkillResult.ok(value="hello", skill_name="classify", skill_version="1.0.0")
        SkillResult.fail(skill_name="classify", skill_version="1.0.0", error=err)
        SkillResult.merge([result1, result2])  # aggregate multiple results
    """
    success: bool
    skill_name: str = ""
    skill_version: str = ""
    value: Optional[T] = None
    error: Optional[Any] = None        # PipelineError subtype
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    @classmethod
    def ok(
        cls,
        value: T,
        *,
        skill_name: str = "",
        skill_version: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "SkillResult[T]":
        """Create a successful skill result."""
        return cls(
            success=True,
            skill_name=skill_name,
            skill_version=skill_version,
            value=value,
            metadata=metadata or {},
        )

    @classmethod
    def fail(
        cls,
        *,
        skill_name: str = "",
        skill_version: str = "",
        error: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "SkillResult[T]":
        """Create a failed skill result with a typed error."""
        return cls(
            success=False,
            skill_name=skill_name,
            skill_version=skill_version,
            error=error,
            metadata=metadata or {},
        )

    # ------------------------------------------------------------------
    # Trace / checkpoint metadata enrichment (P3)
    # ------------------------------------------------------------------

    def with_trace(
        self,
        trace_id: str,
        duration_ms: float = 0.0,
    ) -> "SkillResult[T]":
        """Return a new ``SkillResult`` with trace metadata populated.

        Adds ``trace_id`` and ``duration_ms`` to ``metadata``.

        Args:
            trace_id: The active trace ID.
            duration_ms: Elapsed time for this skill execution.

        Returns:
            A new ``SkillResult`` with enriched metadata.
        """
        self.metadata["trace_id"] = trace_id
        self.metadata["duration_ms"] = duration_ms
        return self

    def with_checkpoint(
        self,
        checkpoint_id: str,
    ) -> "SkillResult[T]":
        """Return a new ``SkillResult`` with checkpoint metadata populated.

        Adds ``checkpoint_id`` to ``metadata``.

        Args:
            checkpoint_id: The checkpoint identifier.

        Returns:
            A new ``SkillResult`` with enriched metadata.
        """
        self.metadata["checkpoint_id"] = checkpoint_id
        return self

    @classmethod
    def merge(
        cls, results: list["SkillResult"]
    ) -> "SkillResult[Dict[str, Any]]":
        """Aggregate multiple ``SkillResult`` instances into one.

        Merges all *results* into a single result whose ``value`` is a
        dict mapping ``skill_name → result.value``. Returns a failed
        result if *results* is empty or ANY result is a failure.

        Args:
            results: List of ``SkillResult`` instances to merge.

        Returns:
            A single ``SkillResult`` with aggregated value or the first
            error encountered.
        """
        if not results:
            from src.engine.exceptions import StageExecutionError
            return cls(
                success=False,
                skill_name="merged",
                error=StageExecutionError(
                    "No skills to merge",
                    stage_name="merge",
                ),
            )

        # Short-circuit on first failure
        for r in results:
            if not r.success:
                return cls(
                    success=False,
                    skill_name="merged",
                    error=r.error or StageExecutionError(
                        "Skill execution failed",
                        stage_name=r.skill_name,
                    ),
                    metadata={"failed_skill": r.skill_name},
                )

        # Merge all successful values
        merged_value: Dict[str, Any] = {}
        for r in results:
            if r.value is not None:
                merged_value[r.skill_name or "unnamed"] = r.value

        return cls(
            success=True,
            skill_name="merged",
            value=merged_value,
            metadata={
                "merged_count": len(results),
                "skills": [r.skill_name for r in results],
            },
        )


# =========================================================================
# SessionContext — aggregate of session prep results
# =========================================================================
@dataclass
class SessionContext:
    """Aggregated results from the session preparation stage."""
    session: Any
    order_id: Optional[str]
    order: Optional[Any]
    summary_order: str
    summary_conversation: str
    order_before: Optional[Dict[str, Any]]


# =========================================================================
# Type aliases for each pipeline stage
# =========================================================================
InputGuardResult = StageResult[str]          # value: truncated message
PrepareSessionResult = StageResult[SessionContext]
ClassificationResult = StageResult[Any]      # value: UserQueryClassifier
RAGResult = StageResult[Any]                 # value: UserQueryClassifier (mutated)
OrderProcessingResult = StageResult[dict]    # value: orchestrator response dict
ResponseGenerationResult = StageResult[str]  # value: response text
LoggingResult = StageResult[None]
SummarizationResult = StageResult[None]
