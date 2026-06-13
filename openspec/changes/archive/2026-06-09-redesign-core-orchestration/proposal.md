# Proposal: Redesign core orchestration: pipeline → LLM planner with tool calling

## Intent

Hardcoded pipeline forces classify on every message, rigid ordering, no inter-skill reflection, dead `decide_skills()`. 5 concrete problems:
- No LLM reflection on which skills to invoke
- classify is mandatory even for trivially inferable messages
- No branching (can't skip rag-retrieve after exact menu match)
- No inter-skill reflection (results don't inform next step)
- `SkillOrchestrator.decide_skills()` exists but is dead code

Replace hardcoded pipeline with an LLM Planner that treats skills as tools, reasons about execution order, and streams thinking transparently.

## Scope

### In Scope
- Planner class (LLM + tool-calling loop, replaces `_run_orchestration_loop` body)
- Skill-as-tool adapter (7 skills → 7 tools from SKILL.md metadata)
- Planner prompt with skill registry descriptions, termination, reflection instructions
- PipelineStreamer: chain-of-thought → visible thinking phases
- Termination: planner calls `respond` tool
- Error handling: skill failures returned as tool errors, planner retries/skips
- Feature flag `use_llm_planner` (default False), both paths coexist
- Tests: planning loop, tool selection, error recovery, termination

### Out of Scope
- Individual skill implementations, SkillRegistry, PipelineStreamer
- Gradio UI, LLM providers, ChromaDB, memory/models
- Parallel execution
- Removing old pipeline (deferred until flag stabilizes)

## Capabilities

### New Capabilities
None — pure orchestration refactor.

### Modified Capabilities
None — no spec-level behavior changes.

## Approach

1. **Feature flag** `use_llm_planner` (default False)
2. **7 tools** from SKILL.md: name, description, JSON input/output schema
3. **Planner prompt**: available skills + intents + contracts, conversation context, instruction to reflect after each call
4. **Classify = tool** (not mandatory): planner calls it only when message is ambiguous
5. **Loop**:
   ```
   1. LLM thinks → returns tool call or `respond`
   2. Tool executes → result fed back to LLM
   3. LLM reflects → repeats or terminates
   ```
6. **Transparency**: chain-of-thought streamed via PipelineStreamer phases
7. **Termination**: `respond` tool with final response text
8. **Errors**: skill failure in tool result → planner retries/skips/falls back

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/core/assistant.py` | Modified | `_run_orchestration_loop` uses Planner when flag on |
| `src/core/agent/planner.py` | New | Planner: tool loader, LLM loop, state machine |
| `src/core/agent/skill_tools.py` | New | Tool adapter: 7 tools from SKILL.md |
| `src/config/environment.py` | Modified | +`use_llm_planner` flag |
| `prompts/planner/` | New | System prompt + instructions |
| `tests/` | New | Planner tests, error scenarios |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Latency increase per turn | High | Prompt constraints ("prefer minimal calls"). Benchmark vs old pipeline |
| Multiple LLM calls per message | Med | Tool calls are cheap. Hard limit 5 calls, then force respond |
| Planner infinite loops | Low | Hard cap (5 calls) + timeout per call |
| Skill execution errors | Med | Error in tool result → planner decides. FALLBACK_ERROR on exhaustion |

## Rollback Plan

1. Toggle `use_llm_planner=false` — old pipeline runs unchanged
2. Delete `planner.py` and `skill_tools.py` if needed
3. No data migration required

## Dependencies

- LLM provider with tool/function calling (DeepSeek, OpenAI, Anthropic, Gemini)
- `SkillRegistry.list_skills()` / `find_by_intent()` (already exist)
- `PipelineStreamer` (already exists)

## Success Criteria

- [ ] "quiero dos tacos" → classify → order-flow → respond (3 calls)
- [ ] "a la plancha" → menu-query → respond (2 calls, no classify)
- [ ] exact menu match skips rag-retrieve
- [ ] All pipeline tests pass with flag off (regression)
- [ ] Latency ≤ 1.5x of old pipeline
- [ ] Planner terminates ≤ 5 tool calls
- [ ] Skill errors handled without crashes
