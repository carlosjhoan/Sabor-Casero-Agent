# Proposal: Single-Stage Thought Generator

## Intent

The ThoughtGenerator uses a **broken two-stage flow**: Stage 1 calls the LLM with `response_format={"type": "text"}` but the prompt (`thought_generator_prompt_v2.0.txt`) instructs the LLM to output JSON. The LLM produces structured JSON anyway; the code treats it as free-text, passing a JSON blob to ActionPlanner instead of clean reasoning. Stage 2 then re-parses ambiguity from that text — a redundant LLM call.

Fix: **single-stage structured output**. One LLM call returns `ThoughtOutput` (reasoning + ambiguity). Remove `_extract_ambiguity()`. Also switch model to `deepseek-v4-flash` (faster, cheaper, better structured output).

## Scope

### In Scope
- Refactor `thought_generator.py` to single-stage structured output using `ThoughtOutput`
- Remove `_extract_ambiguity()` and `_generate_thought_with_retry()`
- Update `orchestrator.py` to consume `thought_output.reasoning`
- Change default model in `environment.py` to `deepseek-v4-flash`
- Update existing test suite + add new single-stage flow tests

### Out of Scope
- Changes to `ActionPlanner` itself (already consumes `thought` as a string, which `.reasoning` provides)
- Changes to response pipeline or other pipeline stages
- Changes to the prompt file (already correct for structured output)

## Capabilities

### New Capabilities
None — pure refactor. No new spec-level behavior.

### Modified Capabilities
None — same contract: ThoughtGenerator produces reasoning + ambiguity. Only the implementation changes.

## Approach

1. Replace the two-stage flow in `ThoughtGenerator.generate_thought()` with a single `chat_completion` call using `response_format={"type": "json_object"}` + `output_format=ThoughtOutput`
2. Parse `ThoughtOutput.reasoning` (str) and `ThoughtOutput.ambiguity` (AmbiguityDeclaration)
3. Return dict with keys `thought` (= `.reasoning`), `ambiguity` (= `.ambiguity`), `success`, `context`
4. Update `orchestrator.py` — already uses `thought_result["thought"]` which becomes `.reasoning`
5. Update `environment.py` — change `llm_model_thought_generator` default to `deepseek-v4-flash`
6. Keep prompt `v2.0.txt` unchanged — already instructs JSON output with `reasoning` + `ambiguity` fields

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/core/order/application/thought_generator.py` | Major refactor | Remove two-stage, add single structured call |
| `src/core/order/application/orchestrator.py` | Update | No structural change — already uses `thought_result["thought"]` |
| `src/config/environment.py` | Update | Change default model string |
| `prompts/thought_generator/thought_generator_prompt_v2.0.txt` | None | Already correct |
| `src/core/order/application/thought_output.py` | None | Already has ThoughtOutput model |
| `src/core/order/application/ambiguity_resolver.py` | None | Already uses `ambiguity_declaration` |
| `tests/order/` | Update | Update existing tests, add new ones |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|-------------|
| ActionPlanner receives structured text instead of clean reasoning | Low | `ThoughtOutput.reasoning` is a plain string field; same contract as before |
| Model change breaks structured output | Low | `deepseek-v4-flash` supports `response_format=json_object`; test first with existing prompt |
| Prompt v2.0 has field name mismatch with ThoughtOutput | Low | Both use `reasoning` + `ambiguity` — verified by reading both files |

## Rollback Plan

1. Revert `environment.py` model default to `deepseek-chat`
2. Restore original two-stage `thought_generator.py` from git
3. Verify pipeline still works with old code path (no breaking interface changes)

## Dependencies

- `deepseek-v4-flash` model availability via API
- No new Python packages needed

## Success Criteria

- [ ] `ThoughtGenerator.generate_thought()` makes exactly **1** LLM call per invocation
- [ ] `thought_result["thought"]` contains clean reasoning text (not JSON blob)
- [ ] `thought_result["ambiguity"]` is an `AmbiguityDeclaration` instance
- [ ] All existing tests pass
- [ ] No regressions in order flow end-to-end
