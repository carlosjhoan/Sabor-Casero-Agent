# Tasks: order-flow-tracker

## Task Breakdown

---

### Task 1: Feature flag + UserPreferences model ✅

**Description**: Add the `use_order_flow_tracker` feature flag to `Settings`, create the `UserPreferences` dataclass with JSON persistence and keyword-based learning, create the `src/core/user/` package.

**Files**:
- **MODIFY** `src/config/environment.py` — add `use_order_flow_tracker: bool = Field(default=False, alias="USE_ORDER_FLOW_TRACKER")` (~3 lines) ✅
- **NEW** `src/core/user/__init__.py` — package init exporting `UserPreferences` (~5 lines) ✅
- **NEW** `src/core/user/preferences.py` — `UserPreferences` dataclass with `save()`, `load()`, `learn_from_observations()`, `to_prompt_context()` (~100 lines) ✅
- **NEW** `data/users/` — create directory (no code) ✅
- **NEW** `tests/user/test_user_preferences.py` — 10 scenarios: learn_from_observations (4 variants), to_prompt_context (2), save/load (3), corruption handling (1) (~100 lines) ✅ — 23 tests covering load/save, Beta-Binomial best guess, merge_from_order, temporal decay, is_active, to_prompt_context

**Depends on**: (none)

**Effort**: ~210 lines

**Risk**: Low

**Key details**:
- `load(user_id, base_path="data/users")` returns default instance if file missing or corrupt — never crashes
- `learn_from_observations()` uses keyword detection: `"sin {ingredient}"` → `avoid_ingredients`, `"bien asada"` → `protein_prefs`, `"extra {item}"` → `extra_items`
- `CONDITIONAL_FIELDS` dict, `ACTION_TO_FIELD` dict, and `KEYWORD_TO_FIELD` dict live in `order_flow_tracker.py`, not in `preferences.py`
- Feature flag defaults to `False` — no behavior change for existing code

**Tests**: Pure unit tests — no LLM, no I/O mocking (use `tmp_path` for save/load)

**Work unit**: `feat(config): add use_order_flow_tracker flag and UserPreferences model`

---

### Task 2: OrderFlowTracker state machine ✅

**Description**: Implement `OrderFlowTracker` — a per-user state machine tracking `PENDING→ASKED→ANSWERED→CONFIRMED` lifecycle for each order field. Includes `CONDITIONAL_FIELDS` logic (address only for delivery, scheduled_time only for pickup), `consume_actions()` to sync from `ActionPlanner`, `resolve_confirmation()` for "Sí" resolution, `get_next_field()` as tracker replacement for `OrderChecklist.get_next_field()`.

**Files**:
- **NEW** `src/core/order/application/order_flow_tracker.py` — `OrderFlowTracker` class + shared constants (`ORDER_FIELDS`, `FIELD_QUESTIONS`, `RETRIEVAL_FIELDS`, `ACTION_TO_FIELD`, `KEYWORD_TO_FIELD`, `CONDITIONAL_FIELDS`) (~200 lines) ✅
- **NEW** `tests/order/test_order_flow_tracker.py` — 20 scenarios from spec section 7 (~250 lines) ✅ — 39 tests across 9 test classes (initial state, consume_actions, get_next_field, resolve_confirmation, all_confirmed, mark operations, conditional fields, checklist status, edge cases)

**Depends on**: Task 1 (imports `UserPreferences` for optional type hint)

**Effort**: ~450 lines

**Risk**: Low-Medium (state transitions need careful edge-case testing)

**Key details**:
- `consume_actions(actions, order_state)` — maps `action_type` via `ACTION_TO_FIELD`, auto-answers fields populated in `order_state`; handles `add_item`/`modify_item` for item-level fields (protein, size, principle); post-condition `_sync_from_order_state()` catches any ASKED field now populated
- `get_next_field()` — skips `CONDITIONAL_FIELDS` whose dependency isn't met (e.g., `address` when `service_type != "delivery"`); returns `None` when all confirmed
- `resolve_confirmation(segments, order_state)` — returns `last_asked` if set, else infers from segment focus via `KEYWORD_TO_FIELD`
- Guard rails: `mark_confirmed` on PENDING → `ValueError`; `mark_asked` on CONFIRMED → warning (no-op); `mark_confirmed` on ASKED → success with warning
- `mark_confirmed("observations")` triggers `_merge_observations_into_prefs()`
- `get_checklist_status()` replaces `OrderChecklist.get_checklist_summary()` with format `[OK]`, `[WAITING]`, `[PENDING]`

**Tests**: All 20 scenarios — no LLM, no I/O, no async. Pure state machine tests.

**Work unit**: `feat(order): add OrderFlowTracker state machine`

---

### Task 3: Remove thought bypass + wire tracker into OrderResponseBuilder ✅

**Description**: Two changes in `order_response_builder.py`:

1. **Unconditional bugfix**: Remove the `thought` bypass at lines 386-390 of `_handle_ordering_async()`. The method currently returns `orchestrator_result.thought` (raw LLM reasoning) directly. New code returns `_build_from_actions(actions, order_state)` when actions exist, otherwise falls through to `_build_checklist_question_async()`.

2. **Feature-flagged wiring**: Add optional `tracker` parameter to `OrderResponseBuilder.__init__()`. Add `_build_from_tracker()` method. Wire tracker into `process_async()` — when tracker is set, route ORDERING and CONFIRMATION paths through `_build_from_tracker`.

**Files**:
- **MODIFY** `src/core/response/order_response_builder.py`:
  - Remove `thought` check in `_handle_ordering_async()` (lines 386-390): delete `if thought: return thought`
  - Add `tracker=None` param to `__init__()`
  - Add `_build_from_tracker()` method (calls `tracker.consume_actions()`, handles CONFIRMATION resolution, calls `tracker.get_next_field()` + `mark_asked()`, does retrieval for fields that need it, falls through to `_build_checklist_question_async()`)
  - Modify `process_async()` to route through `_build_from_tracker` when `self.tracker` is set
  - Modify `_handle_confirmation()` to route through `_build_from_tracker` when tracker is set

**Depends on**: Task 2 (imports and uses `OrderFlowTracker`)

**Effort**: ~85 lines changed in existing file

**Risk**: Medium (changes response flow — verify both flag=True and flag=False paths work)

**Key details**:
- The `thought` bypass removal is **unconditional** — it applies even with `use_order_flow_tracker = False`. It was a latent bug.
- `_build_from_tracker()` follows the spec flow: (1) `consume_actions`, (2) resolve confirmation if CONFIRMATION segment, (3) `get_next_field`, (4) `mark_asked`, (5) build question with retrieval, (6) all-confirmed → confirmation message, (7) fallback to checklist
- When tracker is set, `_handle_confirmation` delegates to `_build_from_tracker` instead of using old logic

**Verification**: 165 existing tests must pass (flag=False path unchanged except thought bypass removal). No test currently asserts that `thought` is returned as the response string.

**Work unit**: `fix(response): remove thought bypass and wire OrderFlowTracker`

---

### Task 4: Suppress stale checklist in ResponseBuilder + wire tracker into assistant pipeline ✅

**Description**: Two files, coordinated change:

**4a. `response_builder.py`**:
- Add `tracker=None` param to `ResponseBuilder.__init__()`, pass to `OrderResponseBuilder` ✅
- In `build_hybrid()` (~line 177): when tracker is active, **suppress** the independent `OrderChecklist.get_next_field()` call — the tracker is now the source of truth ✅
- Pass `tracker.get_checklist_status()` instead of `OrderChecklist.get_checklist_summary()` when tracker is active ✅

**4b. `assistant.py`**:
- Add `self._tracker_cache: Dict[str, OrderFlowTracker] = {}` as instance variable in `SaborCaseroAssistant.__init__()` ✅
- Add `_get_ordering_segments()` helper method ✅
- In `process_message()`, after Stage 4 (Order Processing) and before Stage 5 (Response Generation):
  - If `settings.use_order_flow_tracker` is True and there are ordering segments:
    - Lazy-init tracker per `user_id` in `_tracker_cache` ✅
    - Load `UserPreferences` if not already loaded ✅
- Modify `_stage_response()` to accept optional `tracker` param; inject into `self.response_builder.order_builder.tracker` before calling `build_hybrid()`; persist `tracker.user_prefs.save()` after success ✅

**Files**:
- **MODIFY** `src/core/response/response_builder.py` — ~30 lines changed
- **MODIFY** `src/core/assistant.py` — ~50 lines changed

**Depends on**: Task 3 (uses modified `OrderResponseBuilder` with tracker)

**Effort**: ~80 lines changed

**Risk**: Low-Medium (assistant.py changes are additive with feature flag guard)

**Key details**:
- `response_builder.py` checklist call (line 177) is **only** suppressed when `self.order_builder.tracker is not None` — flag=False means tracker=None, existing `OrderChecklist` path preserved
- `_tracker_cache` keyed by `user_id` — survives across sessions for the same user within process lifetime
- `UserPreferences.save()` called after successful response generation, not on every turn
- No changes to `_stage_classification`, `_stage_rag`, `_stage_order_processing`, or `_stage_logging`

**Verification**: 165 existing tests pass. Add a test verifying that when flag=False, `OrderChecklist.get_next_field()` is still called in the hybrid builder.

**Work unit**: `feat(assistant): wire OrderFlowTracker into pipeline`

---

## File Inventory

| # | File | Action | Est. Lines | Task | Status |
|---|------|--------|-----------|------|--------|
| 1 | `src/config/environment.py` | MODIFY | +3 | T1 | ✅ |
| 2 | `src/core/user/__init__.py` | NEW | 5 | T1 | ✅ |
| 3 | `src/core/user/preferences.py` | NEW | 100 | T1 | ✅ |
| 4 | `data/users/` | NEW | — | T1 | ✅ |
| 5 | `tests/user/test_user_preferences.py` | NEW | 100 | T1 | ✅ |
| 6 | `src/core/order/application/order_flow_tracker.py` | NEW | 200 | T2 | ✅ |
| 7 | `tests/order/test_order_flow_tracker.py` | NEW | 250 | T2 | ✅ |
| 8 | `src/core/response/order_response_builder.py` | MODIFY | +85 | T3 | ✅ |
| 9 | `src/core/response/response_builder.py` | MODIFY | +30 | T4 | ✅ |
| 10 | `src/core/assistant.py` | MODIFY | +50 | T4 | ✅ |

**Total new lines**: ~655 (new files) + ~168 (modified) = **~823 total changed lines**

---

## Work Unit Plan

| Commit | Work Unit | Files | Lines |
|--------|-----------|-------|-------|
| 1 | `feat(config): add use_order_flow_tracker flag and UserPreferences model` | env + user/ + test_user_prefs | ~210 |
| 2 | `feat(order): add OrderFlowTracker state machine` | tracker + test_tracker | ~450 |
| 3 | `fix(response): remove thought bypass and wire OrderFlowTracker` | order_response_builder | ~85 |
| 4 | `feat(assistant): integrate tracker into pipeline` | response_builder + assistant | ~80 |

---

## Execution Order

```
T1 (no deps) ──→ T2 (depends on T1) ──→ T3 (depends on T2) ──→ T4 (depends on T3)
```

All sequential — no parallel batches (each task depends on the previous for imports or API surface).

---

## Work Unit Verification Checklist

Per the work-unit-commits skill, each commit must:

- [ ] Tell a clear story (reviewer understands why from diff + message)
- [ ] Include tests with the behavior they verify
- [ ] Keep the repo in a valid state after each commit
- [ ] Be a candidate chained PR slice (rollback does not revert unrelated work)

---

## Review Workload Forecast

| Metric | Value |
|--------|-------|
| Total new files | 5 (tracker, prefs, user/__init__, 2 test files) |
| Total modified files | 4 (env, order_response_builder, response_builder, assistant) |
| Total changed lines | ~823 |
| Per-commit max lines | ~450 (commit 2 — tracker + tests) |
| Single-PR viability | **No** — exceeds 400-line threshold significantly |
| Recommended approach | **4 chained PRs** (one per commit), stacked to main |

### Delivery Strategy

- **delivery_strategy**: ask-on-risk
- **chain_strategy**: stacked-to-main
- Commit 2 (tracker, ~450 lines) straddles the boundary — consider accepting as-is since it's pure state machine logic with no I/O, or split tests into a separate intermediate commit.

---

## Edge Cases & Gotchas

1. **`response_builder.py` line 177** calls `OrderChecklist.get_next_field()` independently, feeding the LLM prompt. When tracker is active, this **must** be suppressed or the LLM gets stale data. This is the non-obvious finding from the design phase.

2. **`consume_actions` has no 1:1 mapping** for all actions. Action types like `confirm_order`, `cancel_order`, `modify_order` don't map to tracker fields — the tracker simply ignores them.

3. **`observations` is always `_field_is_missing`** in `OrderChecklist`. Tracker handles this correctly — observations goes through the same state machine lifecycle.

4. **Conditional field timing**: If `service_type` is in `ASKED` (not yet `ANSWERED`), `get_next_field` correctly skips both `address` and `scheduled_time` because the dependency value is not known.

5. **Tracker cache lifecycle**: `_tracker_cache` lives as long as the `SaborCaseroAssistant` instance. In the Gradio UI, this means it persists for the process lifetime. On server restart, it resets (preferences survive via JSON).

6. **Pipeline test at line 52** (`"thought": "order processed"`) sets `thought` in the mock orchestrator result. This is fine — the `thought` field still exists in the dict, it's just no longer returned as the response string. The test mocks `build_hybrid` directly, so it's unaffected.
