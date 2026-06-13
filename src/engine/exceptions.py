"""
Typed exception hierarchy for the pipeline (P1 Foundation).

Each exception subtype carries structured context (stage_name, operation,
original exception) so error handling can inspect and react to the specific
failure mode instead of relying on bare ``except Exception``.
"""
from typing import Optional, List, Any
from datetime import datetime


class PipelineError(Exception):
    """Base exception for all pipeline errors."""

    def __init__(
        self,
        message: str,
        *,
        timestamp: Optional[datetime] = None,
    ):
        super().__init__(message)
        self.timestamp = timestamp or datetime.now()


class StageExecutionError(PipelineError):
    """A pipeline stage itself failed during execution.

    Attributes:
        stage_name: Name of the stage that failed.
        original_exception: The underlying exception that caused the failure.
    """

    def __init__(
        self,
        message: str,
        *,
        stage_name: str,
        original_exception: Optional[Exception] = None,
        timestamp: Optional[datetime] = None,
    ):
        super().__init__(message, timestamp=timestamp)
        self.stage_name = stage_name
        self.original_exception = original_exception


class ValidationGateError(PipelineError):
    """A stage's output failed schema/validation checks.

    Attributes:
        stage_name: Name of the stage whose output was rejected.
        violations: Human-readable list of validation failures.
    """

    def __init__(
        self,
        message: str,
        *,
        stage_name: str,
        violations: Optional[List[str]] = None,
        timestamp: Optional[datetime] = None,
    ):
        super().__init__(message, timestamp=timestamp)
        self.stage_name = stage_name
        self.violations = violations or []


class CheckpointError(PipelineError):
    """Checkpoint save/load/clear failed.

    Attributes:
        operation: The checkpoint operation (``"save"``, ``"load"``, ``"clear"``).
        path: Filesystem path of the checkpoint file.
    """

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        path: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ):
        super().__init__(message, timestamp=timestamp)
        self.operation = operation
        self.path = path


class MemoryHubError(PipelineError):
    """A memory store operation failed.

    Attributes:
        memory_type: Which memory store (``"semantic"``, ``"episodic"``, ``"procedural"``).
        operation: The operation that failed (``"store"``, ``"query"``, ``"recall"``).
    """

    def __init__(
        self,
        message: str,
        *,
        memory_type: str,
        operation: str,
        timestamp: Optional[datetime] = None,
    ):
        super().__init__(message, timestamp=timestamp)
        self.memory_type = memory_type
        self.operation = operation


class CacheError(PipelineError):
    """Semantic cache operation failed.

    Attributes:
        cache_key: The cache key involved in the failure.
        operation: The operation that failed (``"lookup"``, ``"store"``, ``"invalidate"``).
    """

    def __init__(
        self,
        message: str,
        *,
        cache_key: str,
        operation: str,
        timestamp: Optional[datetime] = None,
    ):
        super().__init__(message, timestamp=timestamp)
        self.cache_key = cache_key
        self.operation = operation


class OntologyGateError(PipelineError):
    """The ontology validation gate rejected ALL candidates.

    Raised when every candidate dish/item was rejected by the ontology
    validation gate — the pipeline falls back to a clarification response.
    """

    def __init__(
        self,
        message: str,
        *,
        timestamp: Optional[datetime] = None,
    ):
        super().__init__(message, timestamp=timestamp)
