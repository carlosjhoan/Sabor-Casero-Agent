# Proposal: circuit-breakers

## Intent

`process_message()` (220+ lines) has a single `try/except` across 6 pipeline stages.
Any stage failure — transient LLM timeout, ChromaDB outage, orchestrator bug — kills the
entire response. No per-stage error handling, no retry, no graceful degradation.
This adds latency risk and makes the pipeline brittle. We need staged error isolation
so partial failures produce partial responses instead of total silence.

## Scope

### In Scope
- `StageResult[T]` dataclass — typed success/failure per stage
- `retry_with_backoff()` — exponential backoff for transient LLM failures (2 retries)
- Refactor `process_message()` into `_stage_*` methods, each returning `StageResult`
- Graceful degradation rules per stage (see Approach)
- 2 new files: `src/core/agent/stage_result.py`, `src/utils/retry.py`
- 1 new test file: `tests/pipeline/test_pipeline_resilience.py`
- All existing 123 tests pass unchanged — zero behavioral change

### Out of Scope
- Tool registry (Phase 2)
- Meta-reasoner loop (Phase 3)
- Grounding/reflection (Phase 4)
- Persistent reasoning state (Phase 5)
- Any new LLM calls or behavioral changes

## Capabilities

None — this is a pure refactor with no spec-level behavioral changes.

## Approach

**StageResult pattern**: Each `_stage_*` method returns a `StageResult[T]`:
- `.ok(value)` on success, `.fail(message)` on failure
- Downstream stages check `.success` before consuming `.value`
- If a non-critical stage fails, skip its effects and log a warning

**Retry decorator**: `retry_with_backoff(fn, max_retries=2, base_delay=0.5)` wraps
LLM calls. Only retries `TimeoutError` and `ConnectionError`. Other exceptions
propagate immediately to the stage handler.

**Graceful degradation**:

| Stage | If fails... |
|---|---|
| Input Guard (fast) | Critical — reject message |
| Input Guard (LLM) | Allow through (existing) |
| Classification | Critical — return fallback |
| RAG Retrieval | `requires_RAG = False`, mark "RAG unavailable" |
| Order Processing | Skip order, return classification-only response |
| Response Generation | Critical — return FALLBACK_ERROR |
| Summarization | Already fire-and-forget, log only |

**Refactored signature** — unchanged:

```python
async def process_message(self, user_id: str, message: str,
                          session_id: str = None) -> Dict[str, Any]:
```

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/core/agent/stage_result.py` | **New** | `StageResult[T]` dataclass + helper classmethods |
| `src/utils/retry.py` | **New** | `retry_with_backoff()` async function |
| `src/core/assistant.py` | **Modified** | Extract 6 stages into `_stage_*` methods, replace monolithic try/except |
| `tests/pipeline/test_pipeline_resilience.py` | **New** | Mock failures per stage, verify graceful degradation |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Regression in response format | Low | 123 existing tests guard the return contract |
| Retry masking real bugs | Low | Only retries on TimeoutError/ConnectionError, all others propagate |
| Stage ordering mismatch | Low | Existing tests cover the normal flow end-to-end |

## Rollback Plan

Revert commit that touches `assistant.py`, `src/core/agent/`, and `src/utils/retry.py`.
New files have no callers outside this refactor — clean revert. No DB migrations,
no config changes, no schema changes.

## Dependencies

None — pure Python stdlib (dataclasses, asyncio, functools, time).

## Success Criteria

- [ ] All 123 existing tests pass with zero modifications
- [ ] `StageResult` type correctly propagates through all stages
- [ ] `retry_with_backoff` retries on timeout, passes through on success
- [ ] Mocked RAG failure still produces a response (classification-only)
- [ ] Mocked classification failure returns `FALLBACK_ERROR`
- [ ] Mocked order orchestrator failure skips order processing, still responds
