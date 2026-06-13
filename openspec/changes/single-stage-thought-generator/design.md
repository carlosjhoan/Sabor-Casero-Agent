# Design: Single-Stage Thought Generator

## Technical Approach

Replace the two-stage LLM flow (text → ambiguity extraction) with a single structured-output call using `ThoughtOutput`. The prompt v2.0 already instructs JSON output — the fix is aligning `response_format` and adding `output_format=ThoughtOutput` so the pipeline returns clean `.reasoning` instead of a JSON blob.

## Architecture Decisions

### Decision: Single-Stage Structured Output

| Option | Tradeoff |
|--------|----------|
| **Current** (text + second extraction) | Prompt/code misalignment; redundant LLM call; JSON blob leaks to ActionPlanner |
| **Single `ThoughtOutput` call** | One call, no misalignment, clean reasoning |

**Choice**: Single-stage with `output_format=ThoughtOutput`, `response_format={"type": "json_object"}`.
**Rationale**: The prompt already outputs `reasoning` + `ambiguity`. Aligning the API call eliminates the bug and the redundant second call.

### Decision: deepseek-v4-flash as Default Model

**Choice**: Change `llm_model_thought_generator` default from `deepseek-chat` → `deepseek-v4-flash`.
**Rationale**: v4-flash supports `response_format=json_object`, is faster and cheaper, and existing `_extract_ambiguity` already proved structured output works with this provider.

### Decision: No Retry Loop

**Choice**: Remove `_generate_thought_with_retry()` retry logic; single call with no retries.
**Rationale**: Retries were a workaround for the text-mode response. With structured output, the single call either succeeds or fails cleanly. The orchestrator handles errors.

## Data Flow (Before vs After)

```
BEFORE (broken):                    AFTER (fixed):

generate_thought()                  generate_thought()
  ├─ _load_order_context()           ├─ _load_order_context()
  ├─ _prepare_processor_input()      ├─ _prepare_processor_input()
  ├─ _generate_thought_with_retry()  ├─ chat_completion(
  │   prompt=v2.0                       output_format=ThoughtOutput,
  │   response_format="text"            response_format="json_object"
  │   → returns JSON blob            │   → returns ThoughtOutput
  ├─ _extract_ambiguity()            └─ return {
  │   2nd LLM call → AmbiguityDecl         "thought": .reasoning,      ← clean str
  └─ return {                             "ambiguity": .ambiguity,    ← AmbiguityDecl
       "thought": JSON blob,  ✗              ...orchestrator untouched
       "ambiguity": decl                      }
       ... }
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/core/order/application/thought_generator.py` | Modify | Single-stage flow; remove `_extract_ambiguity()`, `_generate_thought_with_retry()`, `AMBIGUITY_EXTRACTOR_PROMPT` |
| `src/config/environment.py` | Modify | Change default to `deepseek-v4-flash` (line 34) |
| `src/core/order/application/orchestrator.py` | None | Already reads `thought_result["thought"]` and `thought_result["ambiguity"]` — no structural change needed |
| `prompts/thought_generator/thought_generator_prompt_v2.0.txt` | None | Already correct for structured output |
| `tests/order/test_thought_generator.py` | **Create** | Cover single-stage flow, fallbacks, error handling |
| `tests/order/test_thought_output.py` | None | Already passing |
| `tests/order/test_ambiguity_resolver.py` | None | Already passing |

## Interfaces / Contracts

```python
# Return contract (unchanged dict shape):
{
    "success": bool,          # True ↓
    "thought": Optional[str], # .reasoning — clean text, NOT JSON
    "ambiguity": Optional[AmbiguityDeclaration],  # .ambiguity
    "context": Optional[Dict],
    "error": Optional[str],
    "processor_input": Optional[str]
}
```

## Error Handling Strategy

| Failure Mode | Behavior |
|---|---|
| LLM returns non-JSON | `_parse_response` raises → caught in `generate_thought` → `success=False` |
| JSON valid but not ThoughtOutput schema | `model_validate_json` raises → try manual extraction of `reasoning` key → if found, use it + safe-default `AmbiguityDeclaration(has_ambiguity=False)` |
| LLM timeout/API error | Exception caught → `success=False`, `error=str(e)` |
| Ambiguity partial failure | If `.reasoning` is recoverable but `.ambiguity` is not → return reasoning + `AmbiguityDeclaration(has_ambiguity=False)` |

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | Single-stage returns ThoughtOutput | Mock LLMClient to return valid ThoughtOutput JSON; verify `.thought` == `.reasoning`, `.ambiguity` is AmbiguityDeclaration |
| Unit | Fallback on parse failure | Mock LLMClient to return invalid JSON; verify `success=False` |
| Unit | Clean reasoning (no JSON blob) | Mock `ThoughtOutput(reasoning="text...")`; verify `thought` has no `{` or `"reasoning"` artifacts |
| Unit | Exactly one LLM call | Spy/mock `chat_completion`; assert called once per `generate_thought()` |
| Unit | Safe default on partial failure | Mock returns `{"reasoning": "ok"}` without `ambiguity`; verify thought preserved + ambiguity safe-default |
| Existing | ThoughtOutput serialization | `test_thought_output.py` — no changes needed |
| Existing | AmbiguityResolver contract | `test_ambiguity_resolver.py` — no changes needed |

## Migration / Rollout

No migration required — atomic refactor. Interface contract unchanged. Can be applied in a single commit.

## Rollback

1. `git revert <commit>` restores `thought_generator.py` and `environment.py`. v2.0 prompt and other files unaffected.
2. Verify pipeline with old two-stage flow.

## Open Questions

None. Design is fully resolved by existing specs and proposal.
