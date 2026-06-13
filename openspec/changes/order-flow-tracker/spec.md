# Spec: order-flow-tracker

## 1. Field State Machine

Each order field tracked by `OrderFlowTracker` follows a four-state lifecycle:

```
PENDING ──→ ASKED ──→ ANSWERED ──→ CONFIRMED
                ↑                          ↑
            (re-ask resets to      (user says "Sí" /
             ASKED)                auto-confirm on next turn)
```

| State | Meaning |
|-------|---------|
| `PENDING` | Never asked — the field has not been presented to the user |
| `ASKED` | Question was posed — waiting for user response. Re-asking the same field keeps it in ASKED |
| `ANSWERED` | User provided data — value is set in the `Order` domain model |
| `CONFIRMED` | User explicitly confirmed — or auto-confirmed after one turn without rejection. Initiate persistence side-effects |

### Transitions

- `PENDING → ASKED`: `mark_asked(field)` called by `ResponseBuilder` before generating the question
- `ASKED → ANSWERED`: Consumed action from `ActionPlanner` sets the field value in `order_state`; or `mark_answered(field, value)` called explicitly
- `ANSWERED → CONFIRMED`: `mark_confirmed(field)` called after:
  - User sends CONFIRMATION (e.g., "Sí") and `resolve_confirmation()` matches `last_asked`
  - User sends data for the next field (auto-confirms the previous one)
  - `consume_actions()` finds the field is populated in `order_state` and the turn advances
- `ASKED → ASKED`: Re-asking the same field (e.g., user didn't understand)
- `ANSWERED → ASKED`: Only if `order_state` field value is later cleared (rollback case)

### Guard rails

- `mark_confirmed` on a `PENDING` field → `ValueError`
- `mark_confirmed` on an `ASKED` field → logs warning, transitions to `CONFIRMED` (lenient — the tracker trusts the caller)
- `mark_asked` on `CONFIRMED` field → logs warning, **no transition** (confirmed is terminal)
- `mark_answered` without prior `ASKED` → transitions directly `PENDING → ANSWERED` (skips ask — happens when ActionPlanner sets a value the tracker didn't ask for)

---

## 2. OrderFlowTracker Class

### File: `src/core/order/application/order_flow_tracker.py` (NEW)

```python
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from src.core.order.domain.models import Order
from src.core.user.preferences import UserPreferences


class FieldState(Enum):
    PENDING = auto()
    ASKED = auto()
    ANSWERED = auto()
    CONFIRMED = auto()


# Tracking fields — matches OrderChecklist.STEPS order exactly
ORDER_FIELDS = [
    "protein",          # PENDING: initial order placement
    "size",             # PENDING: only if item has size variants
    "principle",        # PENDING: side dish
    "customer_name",    # PENDING: who the order is for
    "service_type",     # PENDING: delivery or pickup
    "address",          # PENDING: only if service_type="delivery"
    "scheduled_time",   # PENDING: only if service_type="pickup"
    "payment_method",   # PENDING: how to pay
    "observations",     # PENDING: special notes (always asked last)
]

# Fields that are conditional — only relevant based on other field values
CONDITIONAL_FIELDS = {
    "address": ("service_type", lambda v: v == "delivery"),
    "scheduled_time": ("service_type", lambda v: v == "pickup"),
}

# Mapping from ActionPlanner action_type → tracker field name
ACTION_TO_FIELD = {
    "ask_dish": "protein",
    "ask_size": "size",
    "ask_side": "principle",
    "ask_method": "service_type",
    "ask_address": "address",
    "ask_payment": "payment_method",
    "ask_observation": "observations",
}


class OrderFlowTracker:
    """State machine for order field lifecycle.
    
    Tracks PENDING→ASKED→ANSWERED→CONFIRMED for each order field.
    Consumes ActionPlanner actions to auto-answer fields.
    Provides get_next_field() for ResponseBuilder to know what to ask.
    """

    def __init__(
        self,
        user_id: str,
        user_prefs: Optional[UserPreferences] = None,
    ):
        self.user_id = user_id
        self.user_prefs = user_prefs or UserPreferences(user_id=user_id)
        
        # All fields start PENDING
        self._field_states: Dict[str, FieldState] = {
            f: FieldState.PENDING for f in ORDER_FIELDS
        }
        self._last_asked: Optional[str] = None
        self._asked_order: List[str] = []  # chronological order of ASKED fields
        self._values: Dict[str, Any] = {}  # captured values per field
    
    # ── Core API ──────────────────────────────────────────────────────

    def consume_actions(
        self,
        actions: List[Dict[str, Any]],
        order_state: Optional[Order],
    ) -> None:
        """Process ActionPlanner actions to update field states.
        
        For each action:
        1. Map action_type → field name via ACTION_TO_FIELD
        2. If the field has a value in order_state → mark ANSWERED
        3. For "add_item" / "modify_item" → check protein, size, principle
        
        After actions, scan order_state for any populated fields
        that were ASKED and auto-answer them.
        """
        if not actions:
            return
        
        for action in actions:
            action_type = action.get("action_type", "")
            field = ACTION_TO_FIELD.get(action_type)
            
            if field:
                # Check if the field value is now set in order_state
                if order_state and self._field_is_set(field, order_state):
                    self.mark_answered(field, self._get_field_value(field, order_state))
            
            # Handle item-level fields
            if action_type in ("add_item", "modify_item"):
                if order_state and order_state.items:
                    for item in order_state.items:
                        if item.protein and self._field_states.get("protein") == FieldState.ASKED:
                            self.mark_answered("protein", item.protein)
                        if item.size and self._field_states.get("size") == FieldState.ASKED:
                            self.mark_answered("size", item.size)
                        if item.principle and self._field_states.get("principle") == FieldState.ASKED:
                            self.mark_answered("principle", item.principle)
        
        # Post-condition: scan order_state for any fields with values
        # that are ASKED → auto-answer
        if order_state:
            self._sync_from_order_state(order_state)

    def get_next_field(self) -> Optional[Tuple[str, str, bool]]:
        """Return the next field to ask the user.
        
        Returns (field_name, question, needs_retrieval) or None if all confirmed.
        
        Logic:
        1. Skip fields where conditional dependency is not met
        2. Return first PENDING field in ORDER_FIELDS order
        3. If all CONFIRMED, return None
        """
        for field_name in ORDER_FIELDS:
            state = self._field_states.get(field_name, FieldState.PENDING)
            
            # Skip if already past PENDING
            if state != FieldState.PENDING:
                continue
            
            # Skip conditional fields whose dependency is not met
            if field_name in CONDITIONAL_FIELDS:
                dep_field, dep_pred = CONDITIONAL_FIELDS[field_name]
                dep_value = self._values.get(dep_field)
                if dep_value is None or not dep_pred(dep_value):
                    continue
            
            # This is the next field to ask
            question = FIELD_QUESTIONS.get(field_name, f"¿{field_name}?")
            needs_retrieval = field_name in RETRIEVAL_FIELDS
            return (field_name, question, needs_retrieval)
        
        return None

    def resolve_confirmation(
        self,
        segments: List[Any],
        order_state: Optional[Order],
    ) -> Optional[str]:
        """Resolve a user confirmation ("Sí") to a field.
        
        Priority:
        1. If last_asked is set → return last_asked (user is saying Sí to the last question)
        2. If no last_asked → infer from segment focus keywords
        3. If nothing matches → return None (caller decides)
        """
        if self._last_asked:
            # User is confirming the last thing we asked about
            return self._last_asked
        
        # Infer from segments
        for seg in segments:
            focus = getattr(seg, "focus", str(seg)).lower()
            for keyword, field in KEYWORD_TO_FIELD.items():
                if keyword in focus and self._field_states.get(field) == FieldState.ASKED:
                    return field
        
        return None

    def mark_asked(self, field: str) -> None:
        """Mark a field as ASKED (question was posed to user)."""
        if field not in self._field_states:
            raise ValueError(f"Unknown field: {field}")
        
        current = self._field_states[field]
        if current == FieldState.CONFIRMED:
            # Confirmed is terminal — warn but don't transition
            import logging
            logging.warning(f"Attempted to mark_asked on CONFIRMED field '{field}' — ignored")
            return
        
        self._field_states[field] = FieldState.ASKED
        self._last_asked = field
        if field not in self._asked_order:
            self._asked_order.append(field)

    def mark_answered(self, field: str, value: Any) -> None:
        """Mark a field as ANSWERED (user provided data)."""
        if field not in self._field_states:
            raise ValueError(f"Unknown field: {field}")
        
        self._field_states[field] = FieldState.ANSWERED
        self._values[field] = value

    def mark_confirmed(self, field: str) -> None:
        """Mark a field as CONFIRMED (user explicitly agreed)."""
        if field not in self._field_states:
            raise ValueError(f"Unknown field: {field}")
        
        current = self._field_states[field]
        if current == FieldState.PENDING:
            raise ValueError(
                f"Cannot confirm field '{field}' — it is PENDING (never asked)"
            )
        
        self._field_states[field] = FieldState.CONFIRMED
        
        # Side-effect: merge into user preferences if applicable
        if self.user_prefs and field == "observations":
            self._merge_observations_into_prefs(self._values.get(field, ""))

    def get_checklist_status(self) -> str:
        """Generate LLM context string showing current field statuses.
        
        Format:
        [OK] protein: Tacos al Pastor
        [OK] size: Corriente
        [WAITING] principle
        ...
        """
        lines = []
        for field_name in ORDER_FIELDS:
            state = self._field_states.get(field_name, FieldState.PENDING)
            if state in (FieldState.ANSWERED, FieldState.CONFIRMED):
                value = self._values.get(field_name, "")
                lines.append(f"[OK] {field_name}: {value}")
            elif state == FieldState.ASKED:
                lines.append(f"[WAITING] {field_name}")
            else:
                lines.append(f"[PENDING] {field_name}")
        
        if self.all_confirmed:
            lines.append("[READY] Pedido listo para confirmar")
        
        return "\n".join(lines)
    
    # ── Properties ─────────────────────────────────────────────────────

    @property
    def last_asked(self) -> Optional[str]:
        return self._last_asked

    @property
    def field_states(self) -> Dict[str, FieldState]:
        return dict(self._field_states)

    @property
    def all_confirmed(self) -> bool:
        """Return True if all applicable fields are CONFIRMED."""
        for field_name in ORDER_FIELDS:
            state = self._field_states.get(field_name, FieldState.PENDING)
            
            # Skip conditional fields whose dependency is not met
            if field_name in CONDITIONAL_FIELDS:
                dep_field, dep_pred = CONDITIONAL_FIELDS[field_name]
                dep_value = self._values.get(dep_field)
                if dep_value is None or not dep_pred(dep_value):
                    continue
            
            if state != FieldState.CONFIRMED:
                return False
        
        return True

    # ── Internal helpers ───────────────────────────────────────────────

    def _sync_from_order_state(self, order: Order) -> None:
        """Scan order_state and auto-answer any ASKED fields that now have values."""
        for field_name in ORDER_FIELDS:
            if self._field_states.get(field_name) == FieldState.ASKED:
                if self._field_is_set(field_name, order):
                    value = self._get_field_value(field_name, order)
                    self.mark_answered(field_name, value)

    def _field_is_set(self, field: str, order: Order) -> bool:
        """Check if a field has a value in the Order domain model.
        
        Mirrors OrderChecklist._field_is_missing() logic (negated).
        """
        if field == "protein":
            return any(i.protein for i in order.items)
        if field == "size":
            return any(i.size for i in order.items)
        if field == "principle":
            return any(i.principle for i in order.items)
        if field == "customer_name":
            return bool(order.customer_id)
        if field == "service_type":
            return bool(order.service)
        if field == "address":
            return bool(
                order.service
                and order.service.category.value == "delivery"
                and order.address
            )
        if field == "scheduled_time":
            return bool(
                order.service
                and order.service.category.value == "pickup"
                and order.service.details.scheduled_time
            )
        if field == "payment_method":
            return bool(order.payment_method)
        if field == "observations":
            return bool(order.observations)
        return False

    def _get_field_value(self, field: str, order: Order) -> Any:
        """Extract field value from Order domain model.
        
        Mirrors OrderChecklist._get_field_value().
        """
        if field == "protein":
            for item in order.items:
                if item.protein:
                    return item.protein
        elif field == "size":
            for item in order.items:
                if item.size:
                    return item.size
        elif field == "principle":
            for item in order.items:
                if item.principle:
                    return item.principle
        elif field == "customer_name":
            return order.customer_id or ""
        elif field == "service_type":
            return order.service.type_name if order.service else ""
        elif field == "address":
            return order.address or ""
        elif field == "scheduled_time":
            if order.service and order.service.category.value == "pickup":
                dt = order.service.details.scheduled_time
                return dt.strftime("%H:%M") if dt else ""
            return ""
        elif field == "payment_method":
            return order.payment_method or ""
        elif field == "observations":
            return ", ".join(order.observations) if order.observations else ""
        return ""

    def _merge_observations_into_prefs(self, observations_text: str) -> None:
        """Parse observations text and merge learning into user preferences."""
        if not observations_text or not self.user_prefs:
            return
        # Delegate to UserPreferences
        self.user_prefs.learn_from_observations(observations_text)


# Shared constants (co-located with tracker for single source of truth)
FIELD_QUESTIONS = {
    "protein": "¿Qué plato deseas ordenar?",
    "size": "¿Qué tamaño prefieres? (Corriente o Mini)",
    "principle": "¿Qué principio prefieres?",
    "customer_name": "¿A nombre de quién?",
    "service_type": "¿Delivery o pasas a recoger?",
    "address": "¿Cuál es la dirección de entrega?",
    "scheduled_time": "¿A qué hora pasas a recoger?",
    "payment_method": "¿Cómo vas a pagar?",
    "observations": "¿Tienes alguna observación?",
}

RETRIEVAL_FIELDS = [
    "protein", "size", "principle", "service_type",
    "scheduled_time", "payment_method", "address",
]

KEYWORD_TO_FIELD = {
    "delivery": "service_type", "domicilio": "service_type",
    "recoger": "service_type", "dirección": "address",
    "direccion": "address", "pagar": "payment_method",
    "pago": "payment_method", "efectivo": "payment_method",
}
```

### Behavior details

**`consume_actions`** — called after `ActionPlanner.plan_and_execute()` returns:
1. Iterate actions; for each:
   - If `action_type` maps to a field via `ACTION_TO_FIELD` and `order_state` has that field populated → `mark_answered(field, value)`
   - If `action_type` is `add_item` / `modify_item` → check item-level fields (protein, size, principle)
2. After the loop, scan `order_state` for any ASKED field that is now populated → auto-answer
3. Does NOT modify `ActionPlanner` or its output

**`get_next_field`** — replaces `OrderChecklist.get_next_field()` when flag is on:
1. Walk `ORDER_FIELDS` in order
2. Return first field in `PENDING` state (skip conditionally irrelevant fields)
3. Return `None` when all applicable fields are `CONFIRMED`

**`resolve_confirmation`** — called when classification has `CONFIRMATION`:
1. If `last_asked` set → return it (user is confirming the last question)
2. If no `last_asked` → check segment focus against keyword map
3. Return `None` if no match → caller falls back to existing behavior

**`mark_confirmed`** — triggers preference merge side-effect for `observations`

---

## 3. UserPreferences Model

### File: `src/core/user/preferences.py` (NEW)

```python
from typing import List, Optional
from dataclasses import dataclass, field
import json
import os
import logging

logger = logging.getLogger(__name__)


@dataclass
class UserPreferences:
    """Per-user preference profile persisted as JSON.
    
    File location: data/users/{user_id}/preferences.json
    Loaded at session start, saved after CONFIRMED observations.
    """

    user_id: str
    protein_prefs: List[str] = field(default_factory=list)
    avoid_ingredients: List[str] = field(default_factory=list)
    extra_items: List[str] = field(default_factory=list)
    preferred_payment: Optional[str] = None
    known_addresses: List[str] = field(default_factory=list)

    # ── Persistence ────────────────────────────────────────────────────

    def save(self, base_path: str = "data/users") -> None:
        """Persist preferences to JSON file."""
        user_dir = os.path.join(base_path, self.user_id)
        os.makedirs(user_dir, exist_ok=True)
        file_path = os.path.join(user_dir, "preferences.json")
        
        data = {
            "user_id": self.user_id,
            "protein_prefs": self.protein_prefs,
            "avoid_ingredients": self.avoid_ingredients,
            "extra_items": self.extra_items,
            "preferred_payment": self.preferred_payment,
            "known_addresses": self.known_addresses,
        }
        
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"Saved preferences for user '{self.user_id}' → {file_path}")

    @classmethod
    def load(cls, user_id: str, base_path: str = "data/users") -> "UserPreferences":
        """Load preferences from JSON file. Return defaults if not found."""
        file_path = os.path.join(base_path, user_id, "preferences.json")
        
        if not os.path.exists(file_path):
            logger.info(f"No preferences found for user '{user_id}' — using defaults")
            return cls(user_id=user_id)
        
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            return cls(
                user_id=data.get("user_id", user_id),
                protein_prefs=data.get("protein_prefs", []),
                avoid_ingredients=data.get("avoid_ingredients", []),
                extra_items=data.get("extra_items", []),
                preferred_payment=data.get("preferred_payment"),
                known_addresses=data.get("known_addresses", []),
            )
        except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
            logger.warning(f"Failed to load preferences for '{user_id}': {e}")
            return cls(user_id=user_id)

    # ── Learning ───────────────────────────────────────────────────────

    def learn_from_observations(self, observations_text: str) -> None:
        """Parse free-text observations and extract preference signals.
        
        Detection rules (simple keyword-based):
        - "bien asada", "término", "cocido" → protein_prefs
        - "sin {ingredient}", "no {ingredient}" → avoid_ingredients
        - "extra {item}" → extra_items
        """
        text = observations_text.lower()
        
        # Protein preferences
        prefs_keywords = [
            "bien asada", "bien cocido", "término", "punto término",
            "poco cocido", "jugoso",
        ]
        for kw in prefs_keywords:
            if kw in text and kw not in self.protein_prefs:
                self.protein_prefs.append(kw)
        
        # Avoid ingredients
        import re
        avoid_patterns = [
            r"sin\s+(\w+)",
            r"no\s+(?:le\s+)?(?:ponga|pongas|quiero|quisiera)\s+(\w+)",
        ]
        for pattern in avoid_patterns:
            matches = re.findall(pattern, text)
            for m in matches:
                ingredient = m.strip()
                if ingredient and ingredient not in self.avoid_ingredients:
                    self.avoid_ingredients.append(ingredient)
        
        # Extra items
        extra_pattern = r"extra\s+(\w+)"
        extra_matches = re.findall(extra_pattern, text)
        for m in extra_matches:
            item = f"extra {m}"
            if item not in self.extra_items:
                self.extra_items.append(item)

    def merge_order_observations(self, items: List[Any]) -> None:
        """Extract preference signals from existing OrderItem requirements."""
        for item in items:
            for req in getattr(item, "requirements", []):
                self.learn_from_observations(req)

    # ── Formatting ─────────────────────────────────────────────────────

    def to_prompt_context(self) -> str:
        """Generate LLM-usable context string for ResponseBuilder.
        
        Example:
        "Preferencias del cliente: término: bien asada. 
         Evita: vinagre, ensalada. 
         Extras: extra principio. 
         Pago preferido: Efectivo. 
         Direcciones conocidas: Prados del Sur."
        """
        parts = []
        
        if self.protein_prefs:
            parts.append(f"término: {', '.join(self.protein_prefs)}")
        if self.avoid_ingredients:
            parts.append(f"evita: {', '.join(self.avoid_ingredients)}")
        if self.extra_items:
            parts.append(f"extras: {', '.join(self.extra_items)}")
        if self.preferred_payment:
            parts.append(f"pago preferido: {self.preferred_payment}")
        if self.known_addresses:
            parts.append(f"direcciones conocidas: {', '.join(self.known_addresses)}")
        
        if not parts:
            return "Sin preferencias registradas"
        
        return "Preferencias del cliente: " + ". ".join(parts)
```

### File: `src/core/user/__init__.py` (NEW)

```python
# User package — preference models for per-user persistence
from .preferences import UserPreferences

__all__ = ["UserPreferences"]
```

### Persistence contract

| Aspect | Detail |
|--------|--------|
| Path | `data/users/{user_id}/preferences.json` |
| Format | JSON with explicit fields (not Pickle) |
| Load | At `OrderFlowTracker.__init__()` — `UserPreferences.load(user_id)` |
| Save | After `mark_confirmed("observations")` or on pipeline completion |
| Missing file | Load returns defaults (empty pref lists) — never crashes |
| Corruption | JSON decode error → log warning → return defaults |

---

## 4. ResponseBuilder Changes

### File: `src/core/response/order_response_builder.py` (MODIFY)

#### 4.1 Remove `thought` bypass (line 386–390)

**Current code** (lines 386–393):
```python
async def _handle_ordering_async(self, segments, order_state, orchestrator_result):
    if orchestrator_result and orchestrator_result.get("success"):
        thought = orchestrator_result.get("thought", "")
        actions = orchestrator_result.get("actions", [])
        if thought:
            return thought          # ← BUG: returns raw LLM reasoning
        if actions:
            return self._build_from_actions(actions, order_state)
    return await self._build_checklist_question_async(order_state, segments)
```

**New code** (always, even when flag is False — the thought was never meant to be output):
```python
async def _handle_ordering_async(self, segments, order_state, orchestrator_result):
    if orchestrator_result and orchestrator_result.get("success"):
        actions = orchestrator_result.get("actions", [])
        if actions:
            return self._build_from_actions(actions, order_state)
    return await self._build_checklist_question_async(order_state, segments)
```

The `thought` bypass is removed unconditionally — it was a latent bug. The `build_hybrid` pipeline already ignores `thought` (line 186 of `response_builder.py` passes `order_summary`, not `thought`).

#### 4.2 Add optional `tracker` parameter to `OrderResponseBuilder`

```python
class OrderResponseBuilder:
    def __init__(self, extractor=None, tracker=None):
        self.current_order: Optional[Order] = None
        self.extractor = extractor
        self.tracker = tracker          # NEW: Optional OrderFlowTracker
        self.doc_registry = DocumentRegistry()
```

#### 4.3 New method: `_build_from_tracker`

When `settings.use_order_flow_tracker` is True AND `self.tracker` is set:

```python
async def _build_from_tracker(
    self,
    segments: List[Detail],
    order_state: Optional[Order],
    orchestrator_result: Optional[Dict[str, Any]],
) -> str:
    """Build response using OrderFlowTracker state machine.
    
    Flow:
    1. tracker.consume_actions(actions, order_state)  # sync from ActionPlanner
    2. If CONFIRMATION in segments:
         confirmed = tracker.resolve_confirmation(segments, order_state)
         if confirmed:
             tracker.mark_confirmed(confirmed)
    3. next_field = tracker.get_next_field()
    4. If next_field:
         tracker.mark_asked(next_field.name)
         return build_field_question(next_field)
    5. If tracker.all_confirmed:
         return self._generate_confirmation_message(order_state)
    6. Fallback to checklist question
    """
    actions = (orchestrator_result or {}).get("actions", [])
    
    # Step 1: Consume actions from ActionPlanner
    self.tracker.consume_actions(actions, order_state)
    
    # Step 2: Resolve confirmations
    query_types = [seg.query_type for seg in segments]
    if QueryType.CONFIRMATION in query_types:
        confirmed = self.tracker.resolve_confirmation(segments, order_state)
        if confirmed:
            self.tracker.mark_confirmed(confirmed)
    
    # Step 3: Determine next field
    next_field = self.tracker.get_next_field()
    
    if next_field:
        field_name, question, needs_retrieval = next_field
        self.tracker.mark_asked(field_name)
        
        if field_name == "confirm":
            return self._generate_confirmation_message(order_state)
        
        if not needs_retrieval:
            return question
        
        menu_context = await self._retrieve_field_options(field_name)
        if menu_context:
            return f"{question}\n\nTenemos disponibles: {menu_context}"
        return question
    
    # Step 4: All confirmed → summary
    if self.tracker.all_confirmed:
        return self._generate_confirmation_message(order_state)
    
    # Step 5: Fallback
    return await self._build_checklist_question_async(order_state, segments)
```

#### 4.4 Wire into `process_async` method

```python
async def process_async(self, segments, order_state, orchestrator_result):
    self.current_order = order_state
    if not segments:
        return ""
    
    query_types = [seg.query_type for seg in segments]
    
    if QueryType.CANCELLATION in query_types:
        return self._handle_cancellation(segments, order_state)
    
    if QueryType.CONFIRMATION in query_types:
        # If tracker is active, delegate to _build_from_tracker for resolution
        if self.tracker:
            return await self._build_from_tracker(segments, order_state, orchestrator_result)
        return self._handle_confirmation(segments, order_state, orchestrator_result)
    
    if QueryType.CLARIFICATION in query_types:
        return self._handle_clarification(segments, order_state)
    
    # ORDERING path
    if self.tracker:
        return await self._build_from_tracker(segments, order_state, orchestrator_result)
    
    return await self._handle_ordering_async(segments, order_state, orchestrator_result)
```

### File: `src/core/response/response_builder.py` (MODIFY)

#### Add tracker passthrough

```python
class ResponseBuilder:
    def __init__(self, llm_client=None, extractor=None, tracker=None):
        self.order_builder = OrderResponseBuilder(extractor=extractor, tracker=tracker)
        self.info_builder = InfoResponseBuilder()
        self.mixer = ResponseMixer()
        self.llm_client = llm_client
        self.extractor = extractor
```

In `build_hybrid()`, when tracker is active and ordering segments exist:
- The `order_response` is built by `_build_from_tracker` which handles everything
- Remove `OrderChecklist.get_next_field()` call when tracker is set — the tracker is the source of truth
- Pass `tracker.get_checklist_status()` instead of `OrderChecklist.get_checklist_summary()`

---

## 5. Assistant Pipeline Integration

### File: `src/core/assistant.py` (MODIFY)

#### 5.1 Feature flag in `environment.py`

Add to `Settings` class:
```python
# Feature flags
use_order_flow_tracker: bool = Field(default=False, alias="USE_ORDER_FLOW_TRACKER")
```

#### 5.2 Tracker initialization in `process_message`

In `process_message()`, after session preparation and classification, before response generation:

```python
# Tracker instance (lazy init, reuses across turns)
self._tracker_cache: Dict[str, OrderFlowTracker] = {}  # keyed by user_id
```

```python
# After Stage 4 (order processing), before Stage 5 (response):
tracker = None
if settings.use_order_flow_tracker:
    ordering_segments = self._get_ordering_segments(classification.topic_details)
    if ordering_segments:
        if user_id not in self._tracker_cache:
            from src.core.user.preferences import UserPreferences
            prefs = UserPreferences.load(user_id)
            from src.core.order.application.order_flow_tracker import OrderFlowTracker
            self._tracker_cache[user_id] = OrderFlowTracker(
                user_id=user_id, user_prefs=prefs
            )
        tracker = self._tracker_cache[user_id]
```

#### 5.3 Modified `_stage_response` signature

The tracker needs to be passed through the response builder. The `_stage_response` method already takes `orchestrator_result` — the tracker is a separate cross-cutting concern.

**Option A (recommended — minimal change)**: Set tracker on `response_builder.order_builder` before calling `build_hybrid`:

```python
async def _stage_response(self, classification, order, orchestrator_result, message, summary_conversation, tracker=None):
    try:
        stage_start = time.time()
        
        # Inject tracker into order builder if active
        if tracker:
            self.response_builder.order_builder.tracker = tracker
        
        config = STAGE_RETRY_CONFIG.get("response", {})
        response = await retry_with_backoff(
            lambda: self.response_builder.build_hybrid(
                classification=classification,
                order_state=order,
                orchestrator_result=orchestrator_result,
                user_message=message,
                conversation_history=summary_conversation,
                brand_voice_path=settings.brand_voice_path,
                prompt_template_path=settings.response_generation_prompt_path,
                settings=settings,
            ),
            ...
        )
        
        # Persist preferences after successful response
        if tracker and tracker.user_prefs:
            tracker.user_prefs.save()
        
        ...
```

**Option B**: Make tracker an explicit parameter of `build_hybrid`. Option A is simpler and avoids changing the `build_hybrid` signature (which is called from many places).

#### 5.4 Integration in `process_message` pipeline

```python
# STAGE 4: ORDER PROCESSING (unchanged — runs before tracker)
order_result = await self._stage_order_processing(
    classification, session_id, summary_conversation
)
order_after = None
if order_result.success:
    data = order_result.value
    orchestrator_response = data.get("orchestrator_response", {})
    order_after = data.get("order_after")

# Tracked order processing (NEW — between stage 4 and stage 5)
tracker = None
if settings.use_order_flow_tracker:
    ordering_segments = self._get_ordering_segments(classification.topic_details)
    if ordering_segments:
        if user_id not in self._tracker_cache:
            from src.core.user.preferences import UserPreferences
            prefs = UserPreferences.load(user_id)
            from src.core.order.application.order_flow_tracker import OrderFlowTracker
            self._tracker_cache[user_id] = OrderFlowTracker(
                user_id=user_id, user_prefs=prefs
            )
        tracker = self._tracker_cache[user_id]

# STAGE 5: RESPONSE GENERATION (modified — passes tracker)
response_result = await self._stage_response(
    classification,
    order,
    orchestrator_response,
    message,
    summary_conversation,
    tracker=tracker,  # NEW
)
```

#### 5.5 Helper method

```python
def _get_ordering_segments(self, topic_details: List[Detail]) -> List[Detail]:
    """Filter segments relevant to ordering flow."""
    ordering_types = {
        QueryType.ORDERING, QueryType.CONFIRMATION,
        QueryType.CANCELLATION, QueryType.CLARIFICATION,
    }
    return [d for d in topic_details if d.query_type in ordering_types]
```

---

## 6. Feature Flag Behavior

When `settings.use_order_flow_tracker = False` (default):
- `OrderFlowTracker` is never instantiated
- `order_response_builder.py` behavior is **unchanged** except for `thought` bypass removal (which is a bugfix, not a feature)
- `UserPreferences` is never loaded or saved
- All 123 existing tests + 42 resilience tests pass without modification

When `settings.use_order_flow_tracker = True`:
- `OrderFlowTracker` is created per `user_id` and cached
- `UserPreferences` loaded from `data/users/{user_id}/preferences.json`
- `ResponseBuilder` routes through `_build_from_tracker` instead of `_handle_ordering_async`
- `OrderChecklist.get_next_field()` replaced by `tracker.get_next_field()`
- `thought` bypass is already removed (unconditional)
- On pipeline completion, `UserPreferences.save()` persists learned data

---

## 7. Test Scenarios (minimum 15)

### File: `tests/order/test_order_flow_tracker.py` (NEW)

| # | Scenario | Given | Expected |
|---|----------|-------|----------|
| 1 | Initial state — all PENDING | `OrderFlowTracker("user_1")` | All 9 fields in `field_states` are `FieldState.PENDING`, `last_asked` is `None`, `all_confirmed` is `False` |
| 2 | consume_actions with CREATE_ITEM sets protein to ANSWERED | Tracker with protein=ASKED, action `{"action_type": "add_item"}`, order has item with protein="Tacos" | `field_states["protein"] == FieldState.ANSWERED`, `_values["protein"] == "Tacos"` |
| 3 | get_next_field returns size after protein answered | Tracker with protein=ANSWERED, size=PENDING | `get_next_field()` returns `("size", ..., True)` |
| 4 | resolve_confirmation with last_asked="service_type" | Tracker with last_asked="service_type", segments=[CONFIRMATION] | `resolve_confirmation()` returns `"service_type"` |
| 5 | resolve_confirmation infers from segment keywords | Tracker with service_type=ASKED, no last_asked, segments contain "delivery" | `resolve_confirmation()` returns `"service_type"` |
| 6 | resolve_confirmation returns None when nothing matches | Tracker with no last_asked, segments=["gracias"] | `resolve_confirmation()` returns `None` |
| 7 | all_confirmed = True after all fields confirmed | All 9 fields set to CONFIRMED | `all_confirmed` is `True` |
| 8 | all_confirmed = False with pending fields | Only protein=CONFIRMED, rest PENDING | `all_confirmed` is `False` |
| 9 | mark_asked twice on same field stays ASKED | field ASKED → `mark_asked("protein")` | Stays `FieldState.ASKED`, `last_asked` still `"protein"` |
| 10 | mark_confirmed on PENDING field raises ValueError | protein=PENDING → `mark_confirmed("protein")` | Raises `ValueError` |
| 11 | mark_confirmed on ASKED field succeeds with warning | protein=ASKED → `mark_confirmed("protein")` | Transitions to `CONFIRMED` (no crash) |
| 12 | Conditional: delivery → address is relevant | service_type=ANSWERED with value "delivery" | `get_next_field()` returns `("address", ..., True)` |
| 13 | Conditional: pickup → scheduled_time is relevant | service_type=ANSWERED with value "pickup" | `get_next_field()` returns `("scheduled_time", ..., True)` |
| 14 | Conditional: address is skipped for pickup | service_type=ANSWERED with value "pickup" | `get_next_field()` does NOT return address |
| 15 | get_checklist_status formats correctly | Mix of states: protein=CONFIRMED, size=ANSWERED, principle=ASKED | Contains `[OK] protein: ...`, `[OK] size: ...`, `[WAITING] principle`, `[PENDING] customer_name` |
| 16 | consume_actions with multiple actions processes all | 3 actions in list | All matching fields updated |
| 17 | resolve_confirmation with last_asked triggers mark_confirmed | last_asked="service_type", user says "Sí" | `resolve_confirmation()` returns "service_type", caller can then `mark_confirmed("service_type")` |
| 18 | UserPreferences learn_from_observations detects "sin cebolla" | Observations: "sin cebolla, bien asada" | `avoid_ingredients` contains "cebolla", `protein_prefs` contains "bien asada" |
| 19 | UserPreferences load returns defaults for missing file | No `preferences.json` exists | Returns instance with empty lists, no crash |
| 20 | UserPreferences save → load roundtrip | Save prefs with known_addresses=["Prados del Sur"], load again | Loaded instance has `known_addresses == ["Prados del Sur"]` |

### File: `tests/user/test_user_preferences.py` (NEW)

Tests for the `UserPreferences` model:
- `learn_from_observations` detects protein preferences ("bien asada")
- `learn_from_observations` detects avoid ingredients ("sin vinagre")
- `learn_from_observations` detects extra items ("extra principio")
- `learn_from_observations` handles empty string gracefully
- `to_prompt_context` formats correctly with data
- `to_prompt_context` returns fallback when empty
- `save` creates directory and writes valid JSON
- `load` returns defaults when file missing
- `load` handles corrupted JSON gracefully
- Roundtrip: save → load preserves all fields

---

## 8. File Inventory

| File | Action | What |
|------|--------|------|
| `src/core/order/application/order_flow_tracker.py` | **NEW** | `OrderFlowTracker` state machine + `ORDER_FIELDS`, `FIELD_QUESTIONS`, `RETRIEVAL_FIELDS`, `ACTION_TO_FIELD`, `KEYWORD_TO_FIELD`, `CONDITIONAL_FIELDS` constants |
| `src/core/user/preferences.py` | **NEW** | `UserPreferences` dataclass with `save()`, `load()`, `learn_from_observations()`, `to_prompt_context()` |
| `src/core/user/__init__.py` | **NEW** | Package init exporting `UserPreferences` |
| `src/core/response/order_response_builder.py` | **MODIFY** | Remove `thought` bypass in `_handle_ordering_async` (lines 386-390); add optional `tracker` param to `__init__`; add `_build_from_tracker()` method; wire tracker into `process_async()` |
| `src/core/response/response_builder.py` | **MODIFY** | Pass `tracker` to `OrderResponseBuilder`; when tracker active, use `tracker.get_checklist_status()` instead of `OrderChecklist.get_checklist_summary()` |
| `src/core/assistant.py` | **MODIFY** | Add `_tracker_cache` dict; add `_get_ordering_segments()` helper; init tracker in `process_message()` after order processing; pass tracker to `_stage_response()`; persist `UserPreferences` after response |
| `src/config/environment.py` | **MODIFY** | Add `use_order_flow_tracker: bool = Field(default=False, alias="USE_ORDER_FLOW_TRACKER")` |
| `tests/order/test_order_flow_tracker.py` | **NEW** | 20 test scenarios covering state transitions, confirmation resolution, conditional fields, formatting |
| `tests/user/test_user_preferences.py` | **NEW** | 10 test scenarios covering learn, format, persistence roundtrip |
| `data/users/` | **NEW** | Directory for per-user preference JSON files |
| `openspec/changes/order-flow-tracker/spec.md` | **NEW** | This document |

---

## 9. Work Unit Commit Plan

Following the work-unit-commits skill, commits are organized by deliverable behavior (not by file type):

| Commit | Work Unit | Files |
|--------|-----------|-------|
| 1 | **feat: add OrderFlowTracker state machine** — Core field lifecycle with all transitions, `consume_actions`, `get_next_field`, `resolve_confirmation` | `src/core/order/application/order_flow_tracker.py` + tests in `tests/order/test_order_flow_tracker.py` |
| 2 | **feat: add UserPreferences model with JSON persistence** — Per-user preference profile, learn from observations, save/load roundtrip | `src/core/user/preferences.py`, `src/core/user/__init__.py` + tests in `tests/user/test_user_preferences.py` |
| 3 | **fix: remove thought bypass in OrderResponseBuilder** — Remove `orchestrator_result.thought` return path; add optional tracker param; add `_build_from_tracker` method | `src/core/response/order_response_builder.py` |
| 4 | **feat: wire OrderFlowTracker into assistant pipeline** — Feature flag, tracker init, _stage_response integration, preference persistence on pipeline completion | `src/config/environment.py`, `src/core/assistant.py`, `src/core/response/response_builder.py` |

Each commit keeps tests with the code they verify. Commit 3 is a bugfix that applies regardless of the feature flag.
