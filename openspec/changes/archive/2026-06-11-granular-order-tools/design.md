# Design: Granular Order Tools

## Technical Approach

Expose 6 synthetic order tools on `SkillToolAdapter` (following the `get-full-menu` pattern) that call new CRUD methods on `OrderOrchestrator`. Move `order-flow` skill from Planner-callable to `_AUTOMATIC_SKILLS`. The legacy pipeline (`use_llm_planner=False`) is unchanged — it retains `ThoughtGenerator` and `ActionPlanner._generate_actions()` until the legacy path is formally deprecated.

Key principle: each synthetic tool call is **atomic** — load order, apply mutation, save, return result. No intermediate LLM calls, no action batching.

---

## Architecture Decisions

### Decision 1: CRUD methods live on OrderOrchestrator

| Option | Tradeoff | Decision |
|--------|----------|----------|
| New `OrderCommandHandler` class | Cleaner SRP but adds another DI binding | ❌ |
| Expose on `ActionPlanner` | Tight coupling, contradicts "remove LLM" goal | ❌ |
| Add to `OrderOrchestrator` | Slightly larger class, but context[`order_orchestrator`] already injected in `skill_tools.py` | ✅ |

**Rationale**: `order_orchestrator` is already in `skill_context` → accessible in `execute_tool()`. Adding 6 thin methods there avoids a new class while keeping DI simple.

### Decision 2: Keep ThoughtGenerator + _generate_actions() for legacy

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Delete both files | Legacy pipeline `use_llm_planner=False` breaks | ❌ |
| Mark deprecated, keep imports | Legacy works, dead code remains | ✅ |

**Rationale**: The proposal says "remove" but the classic pipeline still calls `process_order_intent()` → `ThoughtGenerator` → `ActionPlanner._generate_actions()`. We **deprecate** but do NOT delete — removal waits until the legacy path is retired. The `order-flow` skill continues to work for `use_llm_planner=False`.

### Decision 3: `session_id` added to orchestration context

The `PlannerContext` has `session_id` but `_build_orchestration_context()` does NOT pass it. Synthetic tools need it to load orders. **Fix**: add `"session_id"` entry in the context dict.

---

## Data Flow

```
BEFORE (use_llm_planner=True):
  Planner → order-flow(skill) → OrderOrchestrator
    → ThoughtGenerator.generate_thought()[LLM]
      → ActionPlanner._generate_actions()[LLM]
        → ActionPlanner._apply_actions_to_aggregate()
          → OrderRepository.save()
    → ResponseBuilder (skipped — Planner uses respond)

AFTER (use_llm_planner=True):
  Planner → add-item | remove-item | ... | get-order(synthetic tools)
    → OrderOrchestrator.add_item() / remove_item() / ...
      → Order.add_item() | Order.remove_item() | Order.update_item() | ...
        → OrderRepository.save()
    → respond (final answer, no ResponseBuilder needed)

LEGACY (use_llm_planner=False): UNCHANGED
  classify → order-flow(skill) → OrderOrchestrator.process_order_intent()
    → ThoughtGenerator → ActionPlanner → apply_and_save
    → response-build(skill)
```

---

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/core/agent/skill_tools.py` | Modify | Add 6 synthetic tool defs + dispatch in `execute_tool()`; move `order-flow` to `_AUTOMATIC_SKILLS` |
| `src/core/order/application/orchestrator.py` | Modify | Add 6 public CRUD methods; keep `process_order_intent()` for legacy |
| `src/core/order/application/action_planner.py` | Modify | Keep file, mark `_generate_actions()` as deprecated; no code change to existing methods |
| `src/core/order/application/thought_generator.py` | Modify | Keep file, mark class as deprecated; no code change |
| `src/core/agent/planner.py` | Modify | Add `session_id` to orchestration context dict |
| `skills/order_flow/SKILL.md` | Modify | Document as legacy-only (use_llm_planner=False) |
| `src/core/response/response_builder.py` | None | No changes needed — Planner path uses `respond`, not `response-build` |
| `src/core/assistant.py` | None | No changes needed — `order-flow` skill moved to `_AUTOMATIC_SKILLS`, not referenced by name in Planner path |

---

## Interfaces / Contracts

### Synthetic tool schemas (in `skill_tools.py`)

```python
_ADD_ITEM_TOOL = {
    "type": "function",
    "function": {
        "name": "add-item",
        "description": "Add an item to the current order.",
        "parameters": {
            "type": "object",
            "properties": {
                "protein": {"type": "string", "description": "Main dish / protein"},
                "quantity": {"type": "integer", "description": "Quantity (default 1)"},
                "size": {"type": "string", "enum": ["corriente", "mini"], "description": "Portion size"},
                "principle": {"type": "string", "description": "Side / principle"},
                "requirements": {"type": "array", "items": {"type": "string"}, "description": "Special requests"},
                "unit_price": {"type": "number", "description": "Unit price"},
            },
            "required": ["protein"],
        },
    },
}

_REMOVE_ITEM_TOOL = {
    "type": "function",
    "function": {
        "name": "remove-item",
        "description": "Remove an item from the current order by item_id.",
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "ID of the item to remove"},
            },
            "required": ["item_id"],
        },
    },
}

_UPDATE_ITEM_TOOL = {
    "type": "function",
    "function": {
        "name": "update-item",
        "description": "Update an existing item in the current order.",
        "parameters": {
            "type": "object",
            "properties": {
                "item_id": {"type": "string", "description": "ID of the item to update"},
                "quantity": {"type": "integer"},
                "protein": {"type": "string"},
                "size": {"type": "string", "enum": ["corriente", "mini"]},
                "principle": {"type": "string"},
                "requirements": {"type": "array", "items": {"type": "string"}},
                "unit_price": {"type": "number"},
            },
            "required": ["item_id"],
        },
    },
}

_GET_ORDER_TOOL = {
    "type": "function",
    "function": {
        "name": "get-order",
        "description": "Get the current order summary (items, totals, status).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

_CONFIRM_ORDER_TOOL = {
    "type": "function",
    "function": {
        "name": "confirm-order",
        "description": "Confirm the current order (sets status to confirmed).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

_CANCEL_ORDER_TOOL = {
    "type": "function",
    "function": {
        "name": "cancel-order",
        "description": "Cancel the current order (sets status to cancelled).",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}
```

### OrderOrchestrator new public methods

```python
async def add_item(self, session_id: str, params: dict) -> dict
async def remove_item(self, session_id: str, item_id: str) -> dict
async def update_item(self, session_id: str, item_id: str, changes: dict) -> dict
async def get_order(self, session_id: str) -> dict
async def confirm_order(self, session_id: str) -> dict
async def cancel_order(self, session_id: str) -> dict
```

Each method: gets session → loads order (or creates if needed for add_item) → applies mutation → saves → returns result dict.

### Tool-to-CRUD mapping

| Tool | Orchestrator method | Returns |
|------|-------------------|---------|
| `add-item` | `add_item(session_id, params)` | `{"item_id": ..., "order_summary": ...}` |
| `remove-item` | `remove_item(session_id, item_id)` | `{"removed_item_id": ..., "order_summary": ...}` |
| `update-item` | `update_item(session_id, item_id, changes)` | `{"item_id": ..., "order_summary": ...}` |
| `get-order` | `get_order(session_id)` | `{"order_id": ..., "items": [...], "status": ..., "total": ...}` |
| `confirm-order` | `confirm_order(session_id)` | `{"order_id": ..., "status": "confirmed"}` |
| `cancel-order` | `cancel_order(session_id)` | `{"order_id": ..., "status": "cancelled"}` |

---

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | 6 synthetic tool schemas (params, required fields) | Assert each dict matches expected structure |
| Unit | `list_tools()` excludes `order-flow` | Assert `order-flow` name absent from output |
| Unit | Each OrderOrchestrator CRUD method | Mock repo, verify aggregate mutation + save |
| Integration | Tool dispatch in `execute_tool()` | Call adapter with mock context, verify orchestrator called |
| Regression | Legacy pipeline unchanged | Run all existing tests with `use_llm_planner=False` |

---

## Migration / Rollback

No migration required. `use_llm_planner` defaults to `False` — the new path activates only when explicitly set to `True`. Rollback is a no-op: set `use_llm_planner=False`.

---

## Open Questions

None. All decisions resolved.
