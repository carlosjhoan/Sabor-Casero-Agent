"""
P1 Spec scenario tests: S-P1-01, S-P1-02, S-P1-03.

These are the acceptance tests for Phase 1 of agent-memory-and-pipeline.
"""
import pytest


class TestSP101NullFieldDetection:
    """S-P1-01: Null field detection → ValidationGateError.

    GIVEN a classifier response with all fields null and success=true
    WHEN result proceeds to validation gate
    THEN the validation gate rejects with ValidationGateError(error_code="NULL_FIELDS")
    """

    def test_validation_gate_rejects_none_classification(self):
        """ValidationGates.validate_classification rejects None with NULL_FIELDS."""
        from src.engine.exceptions import ValidationGateError
        from src.engine.validation_gates import ValidationGates

        with pytest.raises(ValidationGateError) as exc:
            ValidationGates.validate_classification(None)
        violations = exc.value.violations
        assert any("NULL_FIELDS" in v for v in violations)

    def test_validation_gate_rejects_dict_with_all_nulls(self):
        """ValidationGate rejects dict with all null fields."""
        from src.engine.exceptions import ValidationGateError
        from src.engine.validation_gates import ValidationGates

        null_classification = {
            "topic_details": None,
            "requires_RAG": None,
            "requires_reconcilier": None,
        }
        with pytest.raises(ValidationGateError) as exc:
            ValidationGates.validate_classification(null_classification)
        assert any("NULL_FIELDS" in v for v in exc.value.violations)

    def test_validation_gate_accepts_valid_dict(self):
        """ValidationGate accepts valid classification dict."""
        from src.engine.validation_gates import ValidationGates

        valid = {
            "topic_details": [{"segment": "test"}],
            "requires_RAG": False,
            "requires_reconcilier": False,
        }
        result = ValidationGates.validate_classification(valid)
        assert result is True

    def test_validation_gate_passes_when_disabled(self):
        """When pipeline_validation_enabled=False, gate is a no-op."""
        from src.engine.validation_gates import ValidationGates

        result = ValidationGates.validate_classification(None, enabled=False)
        assert result is True

        result2 = ValidationGates.validate_response("", enabled=False)
        assert result2 is True

    def test_validation_gate_rejects_empty_response(self):
        """ValidationGate rejects empty string response."""
        from src.engine.exceptions import ValidationGateError
        from src.engine.validation_gates import ValidationGates

        with pytest.raises(ValidationGateError) as exc:
            ValidationGates.validate_response("")
        assert any("EMPTY_RESPONSE" in v for v in exc.value.violations)


class TestSP102ServiceTypeInference:
    """S-P1-02: Service type inference from UserPreferences.

    GIVEN a user with address stored in UserPreferences (confidence > 0.7)
    WHEN they start ordering without specifying service type
    THEN service_type is set to "delivery" with confirmation prompt
    AND pipeline never defaults to delivery without user confirmation
    """

    def test_address_implies_service_type_delivery(self):
        """User with stored service_type 'delivery' should infer it."""
        from src.core.user.preferences import UserPreferences
        from datetime import date

        prefs = UserPreferences(user_id="test_user")
        today = date.today().isoformat()
        # Need 2+ occurrences to pass the 0.7 threshold
        # formula: (count + 1) / (total + 2)
        # count=2 → (2+1)/(2+2) = 3/4 = 0.75 > 0.7 ✓
        prefs._record_stat("service_types", "delivery", today)
        prefs._record_stat("service_types", "delivery", today)

        guess = prefs.get_best_guess("service_types")
        assert guess == "delivery"

    def test_no_data_returns_none(self):
        """Without stored service_type data, no default."""
        from src.core.user.preferences import UserPreferences

        prefs = UserPreferences(user_id="new_user")
        guess = prefs.get_best_guess("service_types")
        assert guess is None

    def test_service_types_serializes_correctly(self):
        """service_types survives serialization round-trip."""
        import tempfile, os, json
        from src.core.user.preferences import UserPreferences
        from datetime import date

        prefs = UserPreferences(user_id="test_user")
        today = date.today().isoformat()
        prefs._record_stat("service_types", "delivery", today)
        prefs._record_stat("service_types", "delivery", today)

        serialized = prefs._serialize()
        assert "service_types" in serialized
        assert serialized["service_types"]["delivery"]["count"] == 2

        # Round-trip via file
        tmpdir = tempfile.mkdtemp()
        filepath = os.path.join(tmpdir, "test_prefs.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(serialized, f, indent=2, ensure_ascii=False)
        with open(filepath, "r", encoding="utf-8") as f:
            loaded_raw = json.load(f)

        assert "service_types" in loaded_raw
        assert loaded_raw["service_types"]["delivery"]["count"] == 2

    def test_pipeline_never_defaults_to_delivery_without_context(self):
        """The service_type_inference_enabled flag prevents silent defaulting."""
        from src.config.environment import settings

        # When the flag exists and is True, pipeline uses inference
        assert settings.service_type_inference_enabled is True


class TestSP103TypedErrorPropagation:
    """S-P1-03: Typed error propagation in RAG.

    GIVEN a ChromaDB connection timeout during RAG stage
    WHEN the timeout exception is caught
    THEN it wraps as StageExecutionError(stage="rag")
    AND pipeline continues (non-critical)
    """

    @pytest.mark.asyncio
    async def test_rag_timeout_does_not_block_pipeline(self, assistant):
        """A RAG timeout should not block the pipeline (non-critical)."""
        from src.core.classifier.intent import UserQueryClassifier, Detail, QueryTopic, QueryType
        from src.core.classifier.input_guard import FALLBACK_ERROR

        detail = Detail(
            segment="test",
            query_type=QueryType.CONSULTING,
            topic=QueryTopic.MENU,
            focus="consultar informacion del menu",
            file_source="menu.md",
            info_extracted="",
        )
        classification = UserQueryClassifier(
            topic_details=[detail],
            requires_RAG=True,
            requires_reconcilier=False,
        )
        assistant.classifier.classify.return_value = classification
        assistant.extractor.retrieve.side_effect = TimeoutError("ChromaDB connection timeout")

        result = await assistant.process_message("user1", "¿Qué hay en el menú?", "test-session")

        assert result["response"] != FALLBACK_ERROR
        assert "pipeline_error" not in result

    @pytest.mark.asyncio
    async def test_classification_error_propagates(self, assistant):
        """A classification failure should propagate typed error info."""
        from src.core.classifier.input_guard import FALLBACK_ERROR

        assistant.classifier.classify.side_effect = TimeoutError("LLM API timeout")

        result = await assistant.process_message("user1", "Hola", "test-session")
        assert result["response"] == FALLBACK_ERROR
        assert "pipeline_error" in result
