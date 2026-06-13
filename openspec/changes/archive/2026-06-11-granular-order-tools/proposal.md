# Proposal: granular-order-tools

## Intent

Eliminate 2 redundant LLM reasoning layers in the order pipeline. `ThoughtGenerator` (1 LLM call) + `ActionPlanner._generate_actions()` (2nd LLM call) do overlapping reasoning: the outer Planner (when `use_llm_planner=True`) already decides what to do. Expose granular CRUD order tools directly to the Planner via synthetic tools, removing the ThoughtGenerator and ActionPlanner LLM calls entirely.

## Scope

### In Scope
- Add 6 synthetic order tools in `SkillToolAdapter`: `add-item`, `remove-item`, `update-item`, `get-order`, `confirm-order`, `cancel-order`
- Remove `ThoughtGenerator` class (dead code)
- Remove `ActionPlanner._generate_actions()` LLM call; expose pure CRUD methods as public API
- Move `order-flow` skill from Planner's tool list to `_AUTOMATIC_SKILLS` (runs automatically, not callable by Planner)
- Wire `order_orchestrator` into `SkillToolAdapter.execute_tool()` context for synthetic tool dispatch
- Simplify `OrderOrchestrator` public API (remove ThoughtGenerator dependency)
- Update `ResponseBuilder` to handle direct tool-call results (no `thought` parsing)
- Legacy pipeline (`use_llm_planner=False`) remains untouched — rollback-safe

### Out of Scope
- Payment gateway, multi-order, UI changes
- `OrderFlowTracker` modifications (continues working as-is)
- `AmbiguityResolver` removal (it can still run in legacy path)

## Capabilities

### New Capabilities
None — no new spec-level behaviors. This is a pure architecture refactor (removing LLM calls, exposing existing CRUD as tools).

### Modified Capabilities
- `orchestration`: Planner tool list changes — `order-flow` skill removed from callable tools, replaced by 6 synthetic order tools. Planner prompt must include the new tool schemas.

## Approach

```
BEFORE (use_llm_planner=True):
  Planner → order-flow skill → ThoughtGenerator(LLM) → ActionPlanner(LLM) → CRUD → response

AFTER (use_llm_planner=True):
  Planner → add-item | remove-item | ... → CRUD → response
           (direct synthetic tools, no intermediate LLM calls)
```

6 synthetic tools in `SkillToolAdapter`: each maps to a public CRUD method extracted from `ActionPlanner` (or directly from `OrderOrchestrator`). The `order-flow` skill moves to `_AUTOMATIC_SKILLS`. Legacy pipeline sees zero changes — `ThoughtGenerator` and `ActionPlanner._generate_actions()` remain importable but unused.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/core/agent/skill_tools.py` | Modified | Add 6 synthetic order tools + exclude `order-flow` from Planner |
| `src/core/order/application/action_planner.py` | Modified | Remove `_generate_actions()` LLM call; expose CRUD publicly |
| `src/core/order/application/thought_generator.py` | Removed | Entire class replaced by direct tool calls |
| `src/core/order/application/orchestrator.py` | Modified | Remove ThoughtGenerator dep; add direct CRUD entry points |
| `src/core/assistant.py` | Modified | Planner path bypasses legacy order pipeline in new flow |
| `src/core/response/response_builder.py` | Modified | Handle direct tool results (no `thought` to parse) |
| `skills/order_flow/SKILL.md` | Modified | Document as legacy-only |
| `tests/` | Modified | New tests for synthetic tool dispatch; existing tests unchanged |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Planner invents invalid tool args | Med | Schemas enforce required params; runtime validation in `execute_tool()` |
| Legacy pipeline breaks from refactor | Low | `use_llm_planner=False` shares zero new code |
| OrderFlowTracker assumes old action format | Med | Tracker consumes `ActionPlanner` actions — only removed in new path; tracker's `consume_actions()` unchanged |

## Rollback Plan

Set `use_llm_planner=False` (default) — legacy pipeline runs untouched. `ThoughtGenerator` and `_generate_actions()` remain importable but dormant. No DB changes, no data migration.

## Dependencies

- `context["order_orchestrator"]` already populated in `SkillToolAdapter.execute_tool()` context
- Synthetic tool pattern already established (`get-full-menu` precedent)

## Success Criteria

- [ ] All 6 granular order tools callable by Planner via `SkillToolAdapter`
- [ ] `ThoughtGenerator` class removed (file deleted)
- [ ] `ActionPlanner._generate_actions()` removed, pure CRUD methods exposed
- [ ] `order-flow` skill in `_AUTOMATIC_SKILLS`, excluded from Planner tool list
- [ ] Legacy pipeline (`use_llm_planner=False`) passes all existing tests with zero changes
- [ ] No new test failures
