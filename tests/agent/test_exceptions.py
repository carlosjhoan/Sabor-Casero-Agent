"""
Tests for the typed PipelineError exception hierarchy (Task 1.1).
"""
import pytest
from datetime import datetime


class TestPipelineErrorHierarchy:
    """Verify the exception hierarchy structure and attributes."""

    def test_pipeline_error_is_base(self):
        """PipelineError is a direct subclass of Exception."""
        from src.engine.exceptions import PipelineError
        assert issubclass(PipelineError, Exception)

    def test_stage_execution_error_inheritance(self):
        """StageExecutionError inherits from PipelineError."""
        from src.engine.exceptions import (
            PipelineError, StageExecutionError,
        )
        assert issubclass(StageExecutionError, PipelineError)

    def test_validation_gate_error_inheritance(self):
        """ValidationGateError inherits from PipelineError."""
        from src.engine.exceptions import (
            PipelineError, ValidationGateError,
        )
        assert issubclass(ValidationGateError, PipelineError)

    def test_checkpoint_error_inheritance(self):
        """CheckpointError inherits from PipelineError."""
        from src.engine.exceptions import (
            PipelineError, CheckpointError,
        )
        assert issubclass(CheckpointError, PipelineError)

    def test_memory_hub_error_inheritance(self):
        """MemoryHubError inherits from PipelineError."""
        from src.engine.exceptions import (
            PipelineError, MemoryHubError,
        )
        assert issubclass(MemoryHubError, PipelineError)

    def test_cache_error_inheritance(self):
        """CacheError inherits from PipelineError."""
        from src.engine.exceptions import (
            PipelineError, CacheError,
        )
        assert issubclass(CacheError, PipelineError)

    def test_ontology_gate_error_inheritance(self):
        """OntologyGateError inherits from PipelineError."""
        from src.engine.exceptions import (
            PipelineError, OntologyGateError,
        )
        assert issubclass(OntologyGateError, PipelineError)

    def test_stage_execution_error_carries_stage_name(self):
        """StageExecutionError stores stage_name and original_exception."""
        from src.engine.exceptions import StageExecutionError
        cause = ValueError("original error")
        err = StageExecutionError(
            "classification failed",
            stage_name="classification",
            original_exception=cause,
        )
        assert err.stage_name == "classification"
        assert err.original_exception is cause
        assert "classification failed" in str(err)

    def test_validation_gate_error_carries_violations(self):
        """ValidationGateError stores stage_name and violations list."""
        from src.engine.exceptions import ValidationGateError
        err = ValidationGateError(
            "validation failed",
            stage_name="rag",
            violations=["null_fields", "empty_value"],
        )
        assert err.stage_name == "rag"
        assert err.violations == ["null_fields", "empty_value"]

    def test_checkpoint_error_carries_operation_and_path(self):
        """CheckpointError stores operation and path."""
        from src.engine.exceptions import CheckpointError
        err = CheckpointError(
            "save failed",
            operation="save",
            path="/tmp/checkpoint.json",
        )
        assert err.operation == "save"
        assert err.path == "/tmp/checkpoint.json"

    def test_memory_hub_error_carries_type_and_operation(self):
        """MemoryHubError stores memory_type and operation."""
        from src.engine.exceptions import MemoryHubError
        err = MemoryHubError(
            "store failed",
            memory_type="semantic",
            operation="store_entity",
        )
        assert err.memory_type == "semantic"
        assert err.operation == "store_entity"

    def test_cache_error_carries_key_and_operation(self):
        """CacheError stores cache_key and operation."""
        from src.engine.exceptions import CacheError
        err = CacheError(
            "lookup failed",
            cache_key="menu_query:123",
            operation="lookup",
        )
        assert err.cache_key == "menu_query:123"
        assert err.operation == "lookup"

    def test_errors_have_timestamp(self):
        """All PipelineError subtypes carry a timestamp."""
        from src.engine.exceptions import (
            StageExecutionError, ValidationGateError, CheckpointError,
            MemoryHubError, CacheError, OntologyGateError,
        )
        now = datetime.now()
        errors = [
            StageExecutionError("msg", stage_name="s"),
            ValidationGateError("msg", stage_name="s"),
            CheckpointError("msg", operation="save"),
            MemoryHubError("msg", memory_type="s", operation="o"),
            CacheError("msg", cache_key="k", operation="o"),
            OntologyGateError("msg"),
        ]
        for err in errors:
            assert hasattr(err, "timestamp")
            # timestamp should be close to now
            diff = abs((err.timestamp - now).total_seconds())
            assert diff < 5, f"{type(err).__name__} timestamp off by {diff}s"

    def test_exception_is_raiseable(self):
        """All exceptions can be raised and caught as PipelineError."""
        from src.engine.exceptions import (
            PipelineError, StageExecutionError, ValidationGateError,
        )
        with pytest.raises(PipelineError):
            raise StageExecutionError("fail", stage_name="stage")
        with pytest.raises(PipelineError):
            raise ValidationGateError("fail", stage_name="stage", violations=[])
