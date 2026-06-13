"""Tests for UserPreferences — Beta-Binomial stats with temporal decay."""
import json
import os
from datetime import date, timedelta
import pytest

from src.core.order.domain.models import (
    Order,
    OrderItem,
    OrderStatus,
)
from src.core.user.preferences import (
    UserPreferences,
    PreferenceStat,
    USER_DATA_DIR,
    DECAY_HALF_LIFE_DAYS,
)
from tests.helpers.fixtures import make_sample_order

# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def patch_user_data_dir(tmp_path, monkeypatch):
    """Redirect USER_DATA_DIR to a temp directory for all tests."""
    monkeypatch.setattr(
        "src.core.user.preferences.USER_DATA_DIR",
        str(tmp_path / "users")
    )
    yield


@pytest.fixture
def prefs_with_history() -> UserPreferences:
    """A preference profile with some history already."""
    today = date.today().isoformat()
    return UserPreferences(
        user_id="history_user",
        payment_methods={
            "efectivo": PreferenceStat(value="efectivo", count=5, last_seen=today),
            "nequi": PreferenceStat(value="nequi", count=2, last_seen=today),
        },
        addresses={
            "prados del sur": PreferenceStat(
                value="Prados del Sur", count=8, last_seen=today
            ),
            "cendas": PreferenceStat(value="Cendas", count=1, last_seen=today),
        },
        protein_prefs={
            "bien asada": PreferenceStat(value="bien asada", count=6, last_seen=today),
        },
        avoid_ingredients={
            "ensalada": PreferenceStat(value="ensalada", count=2, last_seen=today),
        },
        extra_items={
            "extra principio": PreferenceStat(
                value="extra principio", count=3, last_seen=today
            ),
        },
    )


# ── Load / Save ──────────────────────────────────────────────────────────


class TestUserPreferencesLoad:
    def test_load_non_existent_user_returns_fresh(self):
        prefs = UserPreferences.load("nonexistent_user")
        assert prefs.user_id == "nonexistent_user"
        assert prefs.payment_methods == {}
        assert prefs.addresses == {}
        assert prefs.protein_prefs == {}
        assert prefs.avoid_ingredients == {}
        assert prefs.extra_items == {}

    def test_save_and_reload_roundtrip(self):
        today = date.today().isoformat()
        prefs = UserPreferences(
            user_id="test_user",
            payment_methods={
                "efectivo": PreferenceStat(value="efectivo", count=3, last_seen=today),
            },
            addresses={
                "calle 123": PreferenceStat(value="Calle 123", count=1, last_seen=today),
            },
            protein_prefs={
                "bien asada": PreferenceStat(value="bien asada", count=2, last_seen=today),
            },
            avoid_ingredients={
                "cebolla": PreferenceStat(value="cebolla", count=1, last_seen=today),
            },
            extra_items={
                "principio doble": PreferenceStat(
                    value="principio doble", count=2, last_seen=today
                ),
            },
        )
        prefs.save()

        loaded = UserPreferences.load("test_user")
        assert loaded.user_id == "test_user"
        assert loaded.payment_methods["efectivo"].count == 3
        assert loaded.payment_methods["efectivo"].value == "efectivo"
        assert loaded.addresses["calle 123"].value == "Calle 123"
        assert loaded.protein_prefs["bien asada"].count == 2
        assert loaded.avoid_ingredients["cebolla"].count == 1
        assert loaded.extra_items["principio doble"].count == 2

    def test_corrupted_file_falls_back_to_fresh(self):
        filepath = os.path.join(USER_DATA_DIR, "corrupted_user", "preferences.json")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("this is not valid json {{")

        prefs = UserPreferences.load("corrupted_user")
        assert prefs.user_id == "corrupted_user"
        assert prefs.payment_methods == {}


# ── Beta-Binomial best guess ─────────────────────────────────────────────


class TestBestGuess:
    def test_returns_most_frequent(self, prefs_with_history):
        best = prefs_with_history.get_best_guess("payment_methods", threshold=0.6)
        assert best == "efectivo"  # 5 > 2, score = 6/9 ≈ 0.67 >= 0.6

    def test_returns_none_below_threshold(self):
        """A single occurrence with low count is below 0.7 threshold."""
        today = date.today().isoformat()
        prefs = UserPreferences(
            user_id="test",
            payment_methods={
                "efectivo": PreferenceStat(value="efectivo", count=1, last_seen=today),
            },
        )
        best = prefs.get_best_guess("payment_methods", threshold=0.7)
        # Beta(2, 2) = (1+1)/(1+2) = 0.66 < 0.7
        assert best is None

    def test_above_threshold_with_two_occurrences(self):
        """Two occurrences of the same value crosses the threshold."""
        today = date.today().isoformat()
        prefs = UserPreferences(
            user_id="test",
            payment_methods={
                "efectivo": PreferenceStat(value="efectivo", count=2, last_seen=today),
            },
        )
        best = prefs.get_best_guess("payment_methods", threshold=0.7)
        # Beta(3, 2) = (2+1)/(2+2) = 0.75 >= 0.7
        assert best == "efectivo"

    def test_temporal_decay_reduces_confidence(self, prefs_with_history):
        """A stat seen long ago has lower effective score."""
        old_date = (date.today() - timedelta(days=DECAY_HALF_LIFE_DAYS)).isoformat()
        prefs_with_history.payment_methods["efectivo"].last_seen = old_date
        # efektivo: decayed_count = 5 * 0.5^(30/30) = 2.5
        # Total decayed = 2.5 + 2 = 4.5
        # Score = (2.5 + 1) / (4.5 + 2) = 3.5 / 6.5 ≈ 0.538 — below 0.7
        best = prefs_with_history.get_best_guess("payment_methods")
        assert best is None

    def test_old_preference_is_active_within_max_age(self, prefs_with_history):
        """A stat within max_age_days is still active."""
        long_ago = (date.today() - timedelta(days=150)).isoformat()
        prefs_with_history.addresses["prados del sur"].last_seen = long_ago

        assert prefs_with_history.is_active("addresses", "prados del sur", max_age_days=180)

    def test_valid_address_outside_max_age_is_inactive(self, prefs_with_history):
        """A stat outside max_age_days is inactive."""
        too_old = (date.today() - timedelta(days=190)).isoformat()
        prefs_with_history.addresses["prados del sur"].last_seen = too_old

        assert not prefs_with_history.is_active("addresses", "prados del sur", max_age_days=180)

    def test_get_best_guess_with_score_returns_tuple(self, prefs_with_history):
        value, score = prefs_with_history.get_best_guess_with_score("payment_methods")
        assert value == "efectivo"
        assert 0.0 < score <= 1.0

    def test_empty_category_returns_none(self):
        prefs = UserPreferences(user_id="test")
        assert prefs.get_best_guess("payment_methods") is None

    def test_unknown_category_returns_none(self):
        prefs = UserPreferences(user_id="test")
        assert prefs.get_best_guess("nonexistent_category") is None


# ── Merge from order ─────────────────────────────────────────────────────


class TestMergeFromOrder:
    def test_merge_extracts_protein_prefs_and_avoid(self):
        item = OrderItem(
            protein="Tacos al Pastor",
            quantity=2,
            unit_price=45.0,
            requirements=["sin cebolla", "bien cocido"],
        )
        object.__setattr__(item, "observations", ["bien asada", "punto término"])

        order = Order(items=[item], status=OrderStatus.CONFIRMED)
        prefs = UserPreferences(user_id="test_user")
        prefs.merge_from_order(order)

        assert prefs.protein_prefs["bien asada"].count == 1
        assert prefs.protein_prefs["punto término"].count == 1
        assert prefs.avoid_ingredients["cebolla"].count == 1

    def test_merge_extracts_extra_items_and_avoid(self):
        item = OrderItem(
            protein="Tacos",
            quantity=1,
            unit_price=45.0,
            requirements=["extra principio", "extra macarrones", "sin ensalada"],
        )
        order = Order(items=[item])
        prefs = UserPreferences(user_id="test_user")
        prefs.merge_from_order(order)

        assert prefs.extra_items["principio"].count == 1
        assert prefs.extra_items["macarrones"].count == 1
        assert prefs.avoid_ingredients["ensalada"].count == 1

    def test_merge_with_address_and_payment(self):
        order = make_sample_order(payment_method="tarjeta")
        prefs = UserPreferences(user_id="test_user")
        prefs.merge_from_order(order)

        assert len(prefs.addresses) == 1
        # preferred_payment is now stored in payment_methods dict
        assert prefs.payment_methods["tarjeta"].count == 1

    def test_merge_deduplicates(self):
        order = make_sample_order(payment_method="efectivo")
        prefs = UserPreferences(user_id="test_user")

        prefs.merge_from_order(order)
        prefs.merge_from_order(order)

        assert len(prefs.addresses) == 1
        assert prefs.addresses[list(prefs.addresses.keys())[0]].count == 2

    def test_merge_increments_count(self):
        """Same value merged twice → count increments, not duplicate entry."""
        order = make_sample_order(payment_method="efectivo")
        prefs = UserPreferences(user_id="test_user")

        prefs.merge_from_order(order)
        prefs.merge_from_order(order)

        assert len(prefs.payment_methods) == 1
        assert prefs.payment_methods["efectivo"].count == 2


# ── Prompt context ────────────────────────────────────────────────────────


class TestToPromptContext:
    def test_empty_preferences_produce_empty_string(self):
        prefs = UserPreferences(user_id="test_user")
        assert prefs.to_prompt_context() == ""

    def test_context_with_best_guesses(self, prefs_with_history):
        context = prefs_with_history.to_prompt_context(threshold=0.5)
        assert "Preferencias de cocción: bien asada" in context
        assert "Evitar: ensalada" in context
        assert "Extra: extra principio" in context
        # efectivo: count=5, total_decayed=7 → (5+1)/(7+2) = 0.66 >= 0.5
        assert "Método de pago frecuente: efectivo" in context
        # prados del sur: count=8, total_decayed=9 → (8+1)/(9+2) = 0.81 >= 0.5
        assert "Dirección frecuente: Prados del Sur" in context

    def test_context_shows_confidence_percentage(self, prefs_with_history):
        context = prefs_with_history.to_prompt_context(threshold=0.5)
        # The get_best_guess_with_score returns score = (8+1)/(9+2) = 9/11 ≈ 0.818
        assert "confianza" in context


# ── Temporal decay ────────────────────────────────────────────────────────


class TestTemporalDecay:
    def test_decayed_count_halves_after_one_halflife(self):
        """After 30 days, effective count should be ~50%."""
        old = (date.today() - timedelta(days=DECAY_HALF_LIFE_DAYS)).isoformat()
        stat = PreferenceStat(value="test", count=10, last_seen=old)
        from src.core.user.preferences import UserPreferences as UP
        decayed = UP._decayed_count(stat, date.today())
        # 10 * 0.5^(30/30) = 10 * 0.5 = 5.0
        assert abs(decayed - 5.0) < 0.01

    def test_decayed_count_one_fourth_after_two_halflives(self):
        """After 60 days, effective count should be ~25%."""
        old = (date.today() - timedelta(days=DECAY_HALF_LIFE_DAYS * 2)).isoformat()
        stat = PreferenceStat(value="test", count=8, last_seen=old)
        from src.core.user.preferences import UserPreferences as UP
        decayed = UP._decayed_count(stat, date.today())
        # 8 * 0.5^(60/30) = 8 * 0.25 = 2.0
        assert abs(decayed - 2.0) < 0.01

    def test_recent_preference_beats_old_one_with_higher_count(self):
        """A recent preference with lower raw count should beat an old one
        with higher raw count after decay."""
        today = date.today().isoformat()
        old = (date.today() - timedelta(days=DECAY_HALF_LIFE_DAYS)).isoformat()

        prefs = UserPreferences(
            user_id="test",
            payment_methods={
                "efectivo": PreferenceStat(value="efectivo", count=10, last_seen=old),
                "nequi": PreferenceStat(value="nequi", count=3, last_seen=today),
            },
        )
        # efektivo: decayed = 10 * 0.5 = 5.0, score = (5+1)/(5+3+2) = 6/10 = 0.6
        # nequi: decayed = 3 * 1.0 = 3.0, score = (3+1)/(5+3+2) = 4/10 = 0.4
        best = prefs.get_best_guess("payment_methods", threshold=0.0)
        # At threshold 0.0, returns the highest scoring
        assert best == "efectivo"  # 0.6 > 0.4
