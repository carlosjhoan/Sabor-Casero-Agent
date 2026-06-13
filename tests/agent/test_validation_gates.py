"""
Tests for ValidationGates (Task 1.3).

Validation gates check stage outputs for null/empty values and raise
typed PipelineError subtypes when violations are found.
"""
import pytest


class TestValidationGates:
    """Verify validation gate behavior."""

    def test_import_validation_gates(self):
        from src.engine.validation_gates import ValidationGates
        assert ValidationGates is not None

    def test_validate_classification_rejects_none(self):
        """validate_classification raises ValidationGateError when value is None."""
        from src.engine.validation_gates import ValidationGates
        from src.engine.exceptions import ValidationGateError
        with pytest.raises(ValidationGateError) as exc:
            ValidationGates.validate_classification(None)
        assert any("NULL_FIELDS" in v for v in exc.value.violations)
        assert any("None" in v for v in exc.value.violations)

    def test_validate_classification_rejects_empty_fields(self):
        """validate_classification raises when value has all None fields."""
        from src.engine.validation_gates import ValidationGates
        from src.engine.exceptions import ValidationGateError
        with pytest.raises(ValidationGateError):
            ValidationGates.validate_classification({
                "topic_details": None,
                "requires_RAG": None,
                "requires_reconcilier": None,
            })

    @pytest.mark.asyncio
    async def test_validate_classification_accepts_valid(self):
        """validate_classification passes valid classification data."""
        from src.engine.validation_gates import ValidationGates
        result = await ValidationGates.validate_classification_async({
            "topic_details": [{"segment": "test", "topic": "menu"}],
            "requires_RAG": False,
            "requires_reconcilier": False,
        })
        assert result is True

    def test_validate_response_rejects_empty_string(self):
        """validate_response raises ValidationGateError for empty string."""
        from src.engine.validation_gates import ValidationGates
        from src.engine.exceptions import ValidationGateError
        with pytest.raises(ValidationGateError) as exc:
            ValidationGates.validate_response("")
        assert any("EMPTY_RESPONSE" in v for v in exc.value.violations)

    def test_validate_response_accepts_non_empty(self):
        """validate_response passes non-empty strings."""
        from src.engine.validation_gates import ValidationGates
        result = ValidationGates.validate_response("Hola, ¿qué deseas ordenar?")
        assert result is True

    def test_validate_response_rejects_whitespace_only(self):
        """validate_response rejects whitespace-only strings."""
        from src.engine.validation_gates import ValidationGates
        from src.engine.exceptions import ValidationGateError
        with pytest.raises(ValidationGateError):
            ValidationGates.validate_response("   \n  ")

    def test_validate_stage_result_rejects_null_value(self):
        """validate_stage_result rejects a StageResult with success=True and None value."""
        from src.engine.validation_gates import ValidationGates
        from src.engine.exceptions import ValidationGateError
        from src.engine.stage_result import StageResult
        result = StageResult.ok(value=None)
        with pytest.raises(ValidationGateError):
            ValidationGates.validate_stage_result(result, stage_name="rag")

    def test_validate_stage_result_accepts_valid(self):
        """validate_stage_result passes a valid StageResult."""
        from src.engine.validation_gates import ValidationGates
        from src.engine.stage_result import StageResult
        result = StageResult.ok(value={"data": "valid"})
        assert ValidationGates.validate_stage_result(result, stage_name="rag") is True

    def test_validation_gate_error_carries_violations(self):
        """ValidationGateError from gates includes violation descriptions."""
        from src.engine.validation_gates import ValidationGates
        from src.engine.exceptions import ValidationGateError
        try:
            ValidationGates.validate_classification(None)
        except ValidationGateError as e:
            assert len(e.violations) > 0
            assert any("null" in v.lower() or "none" in v.lower() for v in e.violations)

    def test_validate_response_rejects_none(self):
        """validate_response raises ValidationGateError for None."""
        from src.engine.validation_gates import ValidationGates
        from src.engine.exceptions import ValidationGateError
        with pytest.raises(ValidationGateError):
            ValidationGates.validate_response(None)

    def test_feature_flag_disables_validation(self):
        """When the feature flag is False, gates pass through silently."""
        from src.engine.validation_gates import ValidationGates
        result = ValidationGates.validate_classification(None, enabled=False)
        assert result is True

        result2 = ValidationGates.validate_response("", enabled=False)
        assert result2 is True
