# Proposal: order-flow-tracker

## Intent

The assistant produces empty responses (`assistant_response: ""`) across all ordering turns. Root cause: `OrderResponseBuilder._handle_ordering_async()` returns `orchestrator_result.thought` (LLM reasoning text) directly instead of consulting `OrderChecklist`. The checklist recalculates from `order_state` every turn with no memory of what was asked. Confirmation "Sí" has no `last_asked` context to resolve. User preferences (e.g., "carne bien asada", "sin vinagre") are stored as item-level requirements but lost across sessions. `ActionPlanner` (LLM) and `OrderChecklist` (rules) compete to decide "what to ask next", producing inconsistent or empty output.

## Scope

### In Scope
- `OrderFlowTracker` state machine — field lifecycle PENDING→ASKED→ANSWERED→CONFIRMED
- `last_asked` field to resolve confirmation references
- `UserPreferences` model + JSON persistence per `user_id`
- Remove `thought` bypass in `_handle_ordering_async`, wire tracker into `ResponseBuilder`
- Wire tracker into `assistant.py` pipeline (consumed after ActionPlanner)
- Unit tests: state transitions, "Sí" resolution, preferences read/write
- Feature flag `settings.use_order_flow_tracker` — defaults False

### Out of Scope
- Cross-session conversation history (handled by summarizer)
- Multi-order support, payment gateway, UI changes
- `ActionPlanner` modifications — it continues producing actions; tracker consumes them

## Capabilities

### New Capabilities
- `order-flow-tracker`: Order field state machine tracking PENDING→ASKED→ANSWERED→CONFIRMED lifecycle per field, with `last_asked` resolution for confirmations
- `user-preferences`: Persistent per-user preference profiles (protein doneness, ingredient aversions, extras) stored as JSON in `data/users/{user_id}/preferences.json`

### Modified Capabilities
None — pure new code + integration wiring. Spec-level behavior (how ordering questions are generated) changes only within previously implicit behavior.

## Approach

```
ActionPlanner ──actions[]──→  OrderFlowTracker  ──next_field──→  ResponseBuilder
    (domain)                    (state machine)                    (presentation)
                                     │
                                     ├── field_states: Map<Field, State>
                                     ├── last_asked: Field | None
                                     ├── asked_order: List<Field>
                                     └── user_prefs: UserPreferences (loaded per user_id)
```

**Tracker rules**:
- Consumes `ActionPlanner` actions → auto-answers matching fields → transitions ANSWERED
- `ResponseBuilder` queries `tracker.next_field()` instead of `OrderChecklist.get_next_field()`
- "Sí" lookups: if user says `confirmation` and `last_asked` is set, resolve it as answer to that field
- `UserPreferences` loaded at session start, updated on each ANSWERED→CONFIRMED transition

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/core/order/application/order_flow_tracker.py` | **New** | State machine + field lifecycle |
| `src/core/user/preferences.py` | **New** | UserPreferences model + JSON repo |
| `src/core/user/__init__.py` | **New** | Package init |
| `src/core/response/order_response_builder.py` | **Modified** | Remove `thought` bypass; use tracker |
| `src/core/response/response_builder.py` | **Modified** | Pass tracker; query next_field |
| `src/core/assistant.py` | **Modified** | Init tracker; wire into pipeline |
| `data/users/` | **New** | Directory for preference files |
| `tests/order/test_order_flow_tracker.py` | **New** | State transitions + Sí resolution |
| `tests/user/test_user_preferences.py` | **New** | Preferences CRUD tests |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Tracker diverges from ActionPlanner | Med | Tracker consumes planner actions; conflicts resolved by feature flag |
| Preference persistence corrupts | Low | JSON with validated schema; write on CONFIRMED only |
| Empty responses continue | Low | Tests cover "thought bypass removed" path explicitly |

## Rollback Plan

Set `settings.use_order_flow_tracker = False` to restore current behavior (thought bypass + `OrderChecklist` recalc). New files have no callers when flag is off. No DB migrations.

## Dependencies

- Feature flag must be wired in `src/config/environment.py` (pydantic-settings)
- `OrderResponseBuilder` constructor needs optional `tracker` param

## Success Criteria

- [ ] `OrderFlowTracker` transitions PENDING→ASKED→ANSWERED→CONFIRMED correctly
- [ ] "Sí, porfa" after tracking `last_asked=service_type` resolves to service_type=ANSWERED
- [ ] `_handle_ordering_async` no longer returns `orchestrator_result.thought` directly
- [ ] `UserPreferences` persists and loads across sessions per user_id
- [ ] All existing tests pass when flag is False
