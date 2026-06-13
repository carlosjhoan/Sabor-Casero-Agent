---
name: order-flow
display: Flujo de Pedido
trigger: "user quiere ordenar, modificar, confirmar o cancelar un pedido"
intents: [order_intent, confirmation, cancellation, clarification]
deterministic: false
dependencies: [order_orchestrator]
version: "0.1.0"
deprecated: true
---

# Order-Flow Skill — LEGACY-ONLY

> **⚠️ LEGACY**: This skill is only used when `use_llm_planner=False` (classic pipeline).
> When `use_llm_planner=True`, the 6 synthetic order tools (`add-item`, `remove-item`,
> `update-item`, `get-order`, `confirm-order`, `cancel-order`) replace this skill.

Wraps `OrderOrchestrator.process_order_intent()` for order CRUD operations.

## Contract

- **Input**: `{"ordering_segments": list[dict], "session_id": str, "summary_conversation": str}`
  - Each element in `ordering_segments` is an object with:
    - `segment` (str): The user's raw text segment
    - `focus` (str): What the user wants to do
    - `info_extracted` (dict): Structured info extracted from the segment
    - `query_type` (str): Type of query (ORDERING, CANCELLATION, CLARIFICATION, etc.)
- **Output**: `{"orchestrator_response": dict, "order_after": dict | None}`
- **Behavior**: Delegates to `OrderOrchestrator` → `ThoughtGenerator` → `ActionPlanner`. Handles item add/remove, quantity changes, order confirmation, cancellation. Reloads order state after processing.
- **Errors**: `StageExecutionError` on orchestrator failure. Graceful skip when no ordering segments.

## Guard

Skipped entirely when `ordering_segments` is empty (no ordering intent detected).
