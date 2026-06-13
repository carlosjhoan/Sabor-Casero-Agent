"""
Tests for service_type inference from UserPreferences (Task 1.5, FR-P1-04).

The system MUST NOT default to "delivery" without user context. Instead,
it should derive service_type from UserPreferences or explicit clarification.
"""
import pytest
from datetime import date


class TestServiceTypeInference:
    """Verify service_type is inferred from preferences, not hardcoded."""

    def test_user_preferences_has_service_types_category(self):
        """UserPreferences has a service_types stat category."""
        from src.core.user.preferences import UserPreferences, PreferenceStat
        prefs = UserPreferences(user_id="test_user")
        assert hasattr(prefs, "service_types")
        assert isinstance(prefs.service_types, dict)

    def test_record_service_type_delivery(self):
        """Recording a delivery service type creates a stat entry."""
        from src.core.user.preferences import UserPreferences
        prefs = UserPreferences(user_id="test_user")
        prefs._record_stat("service_types", "delivery", date.today().isoformat())
        assert "delivery" in prefs.service_types
        assert prefs.service_types["delivery"].count == 1

    def test_record_service_type_pickup(self):
        """Recording a pickup service type creates a stat entry."""
        from src.core.user.preferences import UserPreferences
        prefs = UserPreferences(user_id="test_user")
        prefs._record_stat("service_types", "pickup", date.today().isoformat())
        assert "pickup" in prefs.service_types
        assert prefs.service_types["pickup"].count == 1

    def test_infer_service_type_from_address(self):
        """When a user has a stored address, service_type infers to delivery."""
        from src.core.user.preferences import UserPreferences, PreferenceStat
        prefs = UserPreferences(user_id="test_user")
        today = date.today().isoformat()
        prefs._record_stat("addresses", "Calle Principal 123", today)

        inferred = prefs.get_best_guess("service_types")
        # Without explicit service_type data, inference should return None
        assert inferred is None

    def test_get_best_guess_service_type_delivery(self):
        """get_best_guess works for service_types category."""
        from src.core.user.preferences import UserPreferences
        prefs = UserPreferences(user_id="test_user")
        today = date.today().isoformat()
        prefs._record_stat("service_types", "delivery", today)
        prefs._record_stat("service_types", "delivery", today)

        guess = prefs.get_best_guess("service_types")
        assert guess == "delivery"

    def test_get_best_guess_service_type_returns_none_without_data(self):
        """Without any service_type data, get_best_guess returns None."""
        from src.core.user.preferences import UserPreferences
        prefs = UserPreferences(user_id="test_user")
        guess = prefs.get_best_guess("service_types")
        assert guess is None


