# Tasks: Redesign Core Orchestration — Pipeline → LLM Planner with Tool Calling

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~650–700 (5 new files, 3 modified) |
| 400-line budget risk | **High** |
| Chained PRs recommended | **Yes** |
| Suggested split | 3 stacked PRs: (1) infra, (2) planner + wiring, (3) tests |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending — user to decide |

Decision needed before apply: **Yes**
Chained PRs recommended: **Yes**
Chain strategy: **pending**
400-line budget risk: **High**

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Config flag + SkillRegistry enhancement + SkillToolAdapter + prompt | PR 1 | Independent infra — no runtime dependency |
| 2 | Planner class + assistant.py fork on flag | PR 2 | Depends on PR 1 infra |
| 3 | Tests for planner loop, tool adapter, error recovery | PR 3 | Depends on PR 2 code; can start in parallel with PR 2 review |

## Phase 1: Foundation

- [x] 1.1 Add `use_llm_planner: bool = False` to `Settings` in `src/config/environment.py`
- [x] 1.2 Add `get_tool_definitions()` method to `SkillRegistry` returning OpenAI-compatible tool schemas from SKILL.md frontmatter + Contract section
- [x] 1.3 Create `src/core/agent/skill_tools.py` — `SkillToolAdapter.list_tools(registry)` builds 7 tool definitions from SkillRegistry; `execute_tool(name, args, context)` loads skill via `SkillOrchestrator.load_skill().run(input_data)` and returns result dict
- [x] 1.4 Create `prompts/planner/system_prompt.txt` — system prompt with skill descriptions placeholder, reflection rules, cap limit, conversation context, order state, user prefs

### Phase 1 Tests Also Created

- [x] 1.T1 `tests/agent/test_skill_tools.py` — 11 tests covering list_tools (import, delegation, 7-definition count), execute_tool (orchestrator invocation, skill execution, success dict, load failure, skill failure, context injection for classify, context injection for menu-query)
- [x] 1.T2 Added `TestGetToolDefinitions` class (5 tests) to `tests/agent/test_skill_registry.py` — covers tool structure, Contract parsing, skills without Contract, description composition
- [x] 1.T3 Added `TestOrchestrationFlags` class (2 tests) to `tests/agent/test_environment_flags.py` — verifies flag exists and defaults to False

## Phase 2: Core Implementation

- [x] 2.1 Create `src/core/agent/planner.py` — `Planner` class with `PlannerState` enum (THINKING, EXECUTING, REFLECTING, TERMINATED) and async `run()` loop
- [x] 2.2 Implement tool-calling loop: LLM returns tool call → dispatch via `SkillToolAdapter.execute_tool()` → reflect on result → repeat until `respond`
- [x] 2.3 Implement `respond` as synthetic built-in tool that extracts `response` text and terminates the loop
- [x] 2.4 Implement hard cap: `tool_call_count >= 5` forces `respond` with `FALLBACK_ERROR` (R-ORCH-06)
- [x] 2.5 Implement error resilience: tool errors (timeout, skill failure) returned inline → planner retries up to 2x, skips, or falls back; no unhandled exceptions (R-ORCH-08)
- [x] 2.6 Integrate `PipelineStreamer` per design — "Planning" phase per tool call, "Reflection" phase per result, "Fallback" on errors (R-ORCH-07)
- [x] 2.7 Build runtime prompt: inject skill descriptions from registry, conversation summary, order state, user preferences, cap rules

## Phase 3: Integration

- [x] 3.1 Modify `assistant.py` `_run_orchestration_loop()` — fork after classify + candidates, before domain skills: `if settings.use_llm_planner: Planner(...).run(...)` replaces domain skills + response-build
- [x] 3.2 Wire `Planner` instantiation with `llm_client`, `skill_orchestrator`, `streamer`, `settings`, `registry`, `trace_id`; build `PlannerContext` with summaries, preferences, candidates, topic_details

## Phase 4: Testing

- [x] 4.1 `tests/agent/test_skill_tools.py` — assert `list_tools()` returns 7 tools with correct names/descriptions from SKILL.md; assert `execute_tool()` invokes skill and returns result; assert error returns `{"success": false, "error": ...}`
- [x] 4.2 `tests/agent/test_planner.py` — mock LLM returns controlled tool calls → verify correct dispatch; `respond` terminates; hard cap forces `FALLBACK_ERROR` at 5 calls (R-ORCH-06)
- [x] 4.3 Test error recovery: mock skill failure → planner retries up to 2x, then skips and falls back with degradation response (R-ORCH-05, R-ORCH-08)
- [x] 4.4 Regression: `use_llm_planner=False` — all existing pipeline tests pass unchanged (R-ORCH-01)
