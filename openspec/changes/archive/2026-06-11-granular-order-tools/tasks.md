# Tasks: Granular Order Tools

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~640 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 → PR 2 → PR 3 |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | OrderOrchestrator CRUD methods + tests | PR 1 | base=feature/granular-order-tools |
| 2 | Tool schemas + dispatch + AUTOMATIC move | PR 2 | base=PR1 branch |
| 3 | Planner context + deprecation + SKILL.md + integration tests | PR 3 | base=PR2 branch |

## Phase 1: Foundation — OrderOrchestrator CRUD

- [x] 1.1 Write test_order_orchestrator_crud.py: unit tests for add_item/remove_item/update_item/get_order/confirm_order/cancel_order (RED)
- [x] 1.2 Add 6 public CRUD methods + get_or_create_order helper to OrderOrchestrator (GREEN)
- [x] 1.3 Extract common load→mutate→save pattern to _execute_order_operation helper (REFACTOR)

## Phase 2: Core — Synthetic Tool Schemas + Dispatch

- [x] 2.1 Write test_synthetic_tool_schemas.py: assert 6 tool dict structures + required fields; test list_tools() excludes order-flow (RED)
- [x] 2.2 Add 6 schema dicts (_ADD_ITEM_TOOL.._CANCEL_ORDER_TOOL) + dispatch branching in SkillToolAdapter.execute_tool() (GREEN)
- [x] 2.3 Move order-flow to _AUTOMATIC_SKILLS; wire order_orchestrator context injection for synthetic tools

## Phase 3: Planner Context + Deprecation Docs

- [x] 3.1 Add "session_id" entry to _build_orchestration_context() in planner.py
- [x] 3.2 Add @deprecated docstring to ActionPlanner._generate_actions() and ThoughtGenerator class
- [x] 3.3 Update skills/order_flow/SKILL.md: "LEGACY-ONLY — use synthetic tools when use_llm_planner=True"

## Phase 4: Integration + Regression

- [ ] 4.1 Write test_tool_dispatch_integration.py: mock context, verify each tool routes to correct orchestrator CRUD
- [ ] 4.2 Run full regression: pytest with use_llm_planner=False — zero changes expected
- [ ] 4.3 Verify all spec scenarios (R-ORCH-10 simple add-item, multi-step; R-ORCH-11 error semantics)

## Phase 4: Integration + Regression

- [x] 4.1 Write test_tool_dispatch_integration.py: mock context, verify each tool routes to correct orchestrator CRUD
- [x] 4.2 Run full regression: pytest with use_llm_planner=False — zero changes expected
- [x] 4.3 Verify all spec scenarios (R-ORCH-10 simple add-item, multi-step; R-ORCH-11 error semantics)

## Phase 5: Cleanup

- [x] 5.1 Verify order-flow excluded from all tool lists (grep stale references)
- [x] 5.2 Final review: no dangling imports to removed code, coverage ≥ 70%
