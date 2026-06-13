"""
UserPreferences — persistent user profile with Beta-Binomial stats
and temporal decay for stable preference inference.

Each preference is tracked as a PreferenceStat with count + last_seen.
Best-guess uses Beta-Binomial (count + 1, other + 1) + exponential decay:
  score = (decayed_count + 1) / (total + 2)
  decay = count * 0.5 ^ (days_since / 30)

This gives reliable signal from N=1 onward and forgets stale preferences
automatically (~50% weight per 30 days without seeing).
"""
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional
from datetime import date
import json
import os
import logging

from src.core.order.domain.models import Order

logger = logging.getLogger(__name__)

USER_DATA_DIR = "data/users"

DECAY_HALF_LIFE_DAYS = 30  # preference weight halves every 30 days without reinforcement
DEFAULT_THRESHOLD = 0.7     # minimum confidence to treat as "stable"


@dataclass
class PreferenceStat:
    """A single preference observation with frequency tracking."""
    value: str
    count: int = 0
    last_seen: Optional[str] = None  # ISO date


@dataclass
class UserPreferences:
    """Per-user preference profile with Beta-Binomial inference.

    Usage:
        prefs = UserPreferences.load("user_123")
        prefs.merge_from_order(completed_order)
        guess = prefs.get_best_guess("payment_methods")
        prefs.save()
    """
    user_id: str
    payment_methods: Dict[str, PreferenceStat] = field(default_factory=dict)
    addresses: Dict[str, PreferenceStat] = field(default_factory=dict)
    protein_prefs: Dict[str, PreferenceStat] = field(default_factory=dict)
    avoid_ingredients: Dict[str, PreferenceStat] = field(default_factory=dict)
    extra_items: Dict[str, PreferenceStat] = field(default_factory=dict)
    service_types: Dict[str, PreferenceStat] = field(default_factory=dict)

    # ── Persistence ──────────────────────────────────────────────────────

    @classmethod
    def load(cls, user_id: str) -> "UserPreferences":
        filepath = cls._filepath(user_id)
        if not os.path.exists(filepath):
            logger.info(f"No preferences found for {user_id}, creating fresh")
            return cls(user_id=user_id)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                raw = json.load(f)
            # Rehydrate dicts of PreferenceStat from serialized form
            for category in cls._stat_categories():
                if category in raw and isinstance(raw[category], dict):
                    raw[category] = {
                        k: PreferenceStat(**v) for k, v in raw[category].items()
                    }
            return cls(**raw)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"Corrupted preferences for {user_id}: {e}, starting fresh")
            return cls(user_id=user_id)

    def save(self, memory_hub=None) -> None:
        """
        Persist preferences to JSON and optionally sync to semantic memory.

        Args:
            memory_hub: Optional :class:`MemoryHub` instance. If provided
                and ``semantic_memory_enabled`` is ``True``, known
                preferences are synced as semantic entities.
        """
        filepath = self._filepath(self.user_id)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self._serialize(), f, indent=2, ensure_ascii=False)
        logger.info(f"Preferences saved for {self.user_id}")

        # P4: Sync to semantic memory
        if memory_hub is not None:
            self._sync_to_memory_hub(memory_hub)

    def _sync_to_memory_hub(self, memory_hub) -> None:
        """
        Sync known preferences to MemoryHub as semantic entities.

        Runs silently — failures are logged but never raised, so a memory
        store issue never breaks preference persistence.
        """
        try:
            from src.config.environment import settings
            if not settings.semantic_memory_enabled:
                return
        except Exception:
            return  # settings not available (e.g. during test bootstrap)

        try:
            from src.core.memory.domain.models_memory import Entity

            today_str = date.today().isoformat()

            # Avoid ingredients → avoid_ingredient entities
            for stat in self.avoid_ingredients.values():
                entity = Entity(
                    entity_type="avoid_ingredient",
                    value=stat.value,
                    user_id=self.user_id,
                    confidence=min(self._get_confidence(stat.count), 1.0),
                    metadata={"last_seen": today_str},
                )
                memory_hub.store(entity)

            # Protein preferences → protein_pref entities
            for stat in self.protein_prefs.values():
                entity = Entity(
                    entity_type="protein_pref",
                    value=stat.value,
                    user_id=self.user_id,
                    confidence=min(self._get_confidence(stat.count), 1.0),
                    metadata={"last_seen": today_str},
                )
                memory_hub.store(entity)

            # Payment method → payment_method entity
            payment, p_score = self.get_best_guess_with_score("payment_methods")
            if payment and p_score >= 0.5:
                entity = Entity(
                    entity_type="payment_method",
                    value=payment,
                    user_id=self.user_id,
                    confidence=p_score,
                    metadata={"last_seen": today_str},
                )
                memory_hub.store(entity)

            # Address → address entity
            addr, a_score = self.get_best_guess_with_score("addresses")
            if addr and a_score >= 0.5:
                entity = Entity(
                    entity_type="address",
                    value=addr,
                    user_id=self.user_id,
                    confidence=a_score,
                    metadata={"last_seen": today_str},
                )
                memory_hub.store(entity)

        except Exception as e:
            logger.warning(f"Failed to sync preferences to MemoryHub: {e}")

    @staticmethod
    def _get_confidence(count: int) -> float:
        """Simple confidence heuristic from raw count."""
        return (count + 1) / (count + 2)  # Beta(1,1) prior

    # ── Core API ─────────────────────────────────────────────────────────

    def get_best_guess(self, category: str, threshold: float = DEFAULT_THRESHOLD) -> Optional[str]:
        """Return the most likely value for a category, or None if below threshold.

        Uses Beta-Binomial with temporal decay:
        score = (decayed_count + 1) / (total_decayed + 2)

        The +1/+2 is the Beta(1,1) prior — gives non-zero signal from N=1.
        """
        stats = self._get_category(category)
        if not stats:
            return None

        total = sum(s.count for s in stats.values())
        if total == 0:
            return None

        today = date.today()
        total_decayed = sum(
            self._decayed_count(s, today) for s in stats.values()
        )

        best_score = 0.0
        best_value = None

        for value, stat in stats.items():
            score = (self._decayed_count(stat, today) + 1) / (total_decayed + 2)
            if score > best_score:
                best_score = score
                best_value = stat.value  # Use original case, not lowercased key

        return best_value if best_score >= threshold else None

    def get_best_guess_with_score(
        self, category: str
    ) -> tuple[Optional[str], float]:
        """Like get_best_guess but returns (value, score) for callers that
        need the raw confidence."""
        stats = self._get_category(category)
        if not stats:
            return None, 0.0

        total = sum(s.count for s in stats.values())
        if total == 0:
            return None, 0.0

        today = date.today()
        total_decayed = sum(
            self._decayed_count(s, today) for s in stats.values()
        )

        best_score = 0.0
        best_value = None

        for value, stat in stats.items():
            score = (self._decayed_count(stat, today) + 1) / (total_decayed + 2)
            if score > best_score:
                best_score = score
                best_value = stat.value  # Use original case, not lowercased key

        return best_value, best_score

    def is_active(self, category: str, value: str, max_age_days: int = 180) -> bool:
        """Check if a specific value in a category is still active (not decayed)."""
        stats = self._get_category(category)
        if not stats or value not in stats:
            return False
        stat = stats[value]
        if stat.count == 0:
            return False
        if stat.last_seen is None:
            return True
        days_since = (date.today() - date.fromisoformat(stat.last_seen)).days
        return days_since <= max_age_days

    def merge_from_order(self, order: Order) -> None:
        """Extract and merge preferences from a completed order."""
        today = date.today().isoformat()

        for item in order.items or []:
            # Observations: protein preferences
            for obs in (getattr(item, "observations", None) or []):
                obs_lower = obs.lower()
                if any(kw in obs_lower for kw in ["asada", "asado", "cocido", "termino", "punto"]):
                    self._record_stat("protein_prefs", obs, today)

            # Requirements: avoid/extra items
            for req in item.requirements or []:
                req_lower = req.lower()
                if req_lower.startswith("sin "):
                    ingredient = req[4:].strip()
                    if ingredient:
                        self._record_stat("avoid_ingredients", ingredient, today)
                elif req_lower.startswith("extra "):
                    extra = req[5:].strip()
                    if extra:
                        self._record_stat("extra_items", extra, today)

        # Address
        if (order.service
                and order.service.category.value == "delivery"
                and order.address):
            self._record_stat("addresses", order.address, today)

        # Payment method
        if order.payment_method:
            self._record_stat("payment_methods", order.payment_method, today)

    def to_prompt_context(self, threshold: float = 0.5) -> str:
        """Format known preferences for LLM prompt injection.

        Uses a softer threshold (0.5) because this is context, not a decision.
        """
        parts = []

        # Protein cooking preferences (top 3 by count)
        if self.protein_prefs:
            sorted_prefs = sorted(
                self.protein_prefs.values(), key=lambda x: x.count, reverse=True
            )[:3]
            active = [
                s.value for s in sorted_prefs
                if self.is_active("protein_prefs", s.value, max_age_days=180)
            ]
            if active:
                parts.append(f"Preferencias de cocción: {', '.join(active)}")

        # Avoid ingredients
        active_avoid = [
            v.value for v in self.avoid_ingredients.values()
            if self.is_active("avoid_ingredients", v.value, max_age_days=180)
        ]
        if active_avoid:
            parts.append(f"Evitar: {', '.join(active_avoid)}")

        # Extra items
        active_extra = [
            v.value for v in self.extra_items.values()
            if self.is_active("extra_items", v.value, max_age_days=180)
        ]
        if active_extra:
            parts.append(f"Extra: {', '.join(active_extra)}")

        # Best guess payment
        payment, p_score = self.get_best_guess_with_score("payment_methods")
        if payment and p_score >= threshold:
            parts.append(f"Método de pago frecuente: {payment} (confianza {p_score:.0%})")

        # Best guess address
        addr, a_score = self.get_best_guess_with_score("addresses")
        if addr and a_score >= threshold:
            parts.append(f"Dirección frecuente: {addr} (confianza {a_score:.0%})")

        return "\n".join(parts)

    # ── Internal helpers ─────────────────────────────────────────────────

    def _record_stat(self, category: str, value: str, today: str) -> None:
        stats = self._get_category(category)
        value_lower = value.lower()
        if value_lower in stats:
            stats[value_lower].count += 1
            stats[value_lower].last_seen = today
        else:
            stats[value_lower] = PreferenceStat(value=value, count=1, last_seen=today)

    def _get_category(self, category: str) -> Dict[str, PreferenceStat]:
        return getattr(self, category, {})

    @staticmethod
    def _decayed_count(stat: PreferenceStat, today: date) -> float:
        if stat.last_seen is None:
            return float(stat.count)
        days_since = (today - date.fromisoformat(stat.last_seen)).days
        return stat.count * (0.5 ** (days_since / DECAY_HALF_LIFE_DAYS))

    @staticmethod
    def _stat_categories() -> List[str]:
        return [
            "payment_methods", "addresses", "protein_prefs",
            "avoid_ingredients", "extra_items", "service_types",
        ]

    def _serialize(self) -> dict:
        data = {"user_id": self.user_id}
        for category in self._stat_categories():
            stats = self._get_category(category)
            data[category] = {
                k: asdict(v) for k, v in stats.items()
            }
        return data

    @staticmethod
    def _filepath(user_id: str) -> str:
        return os.path.join(USER_DATA_DIR, user_id, "preferences.json")
