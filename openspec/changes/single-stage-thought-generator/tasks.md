# Tasks: Single-Stage Thought Generator

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~270 (40 added + 150 removed in thought_generator.py, 1 in environment.py, ~80 in tests) |
| 400-line budget risk | Low |
| Chained PRs recommended | No |
| Suggested split | Single PR |
| Delivery strategy | ask-on-risk |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: No
Chain strategy: size-exception
400-line budget risk: Low

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | Config + core refactor + tests | PR 1 (single) | Base: main. Tests bundled with code. |

## Phase 1: Config Foundation

- [ ] 1.1 `src/config/environment.py`: change `llm_model_thought_generator` default from `"deepseek-chat"` to `"deepseek-v4-flash"` (line 34).

## Phase 2: Core Refactor

- [ ] 2.1 `src/core/order/application/thought_generator.py`: remove `AMBIGUITY_EXTRACTOR_PROMPT`, `self.max_retries`, `self.temperature_base`, unused imports (`json`, `asyncio`). Remove `_extract_ambiguity()` and `_generate_thought_with_retry()` methods.
- [ ] 2.2 Rewrite `generate_thought()`: single `chat_completion` with `response_format="json_object"` + `output_format=ThoughtOutput`. Extract `.reasoning` as `thought`, `.ambiguity` as `ambiguity`. Keep `_load_order_context()` / `_prepare_processor_input()` unchanged. Update docstrings.
- [ ] 2.3 Verify `orchestrator.py` compatibility: confirm `thought_result["thought"]` and `thought_result["ambiguity"]` key consumption — no code change needed.

## Phase 3: Testing

- [ ] 3.1 Create `tests/order/test_thought_generator.py`: happy path (valid ThoughtOutput → clean `.thought`, `.ambiguity` is `AmbiguityDeclaration`). Run `pytest tests/order/test_thought_generator.py -v`.
- [ ] 3.2 Add test: LLM returns non-JSON → `success=False`, `thought=None`, `ambiguity=None`.
- [ ] 3.3 Add test: response has `reasoning` but invalid ambiguity → preserves reasoning + safe-default `AmbiguityDeclaration(has_ambiguity=False)`.
- [ ] 3.4 Add test: exactly 1 LLM call per `generate_thought()` invocation (spy on `chat_completion`).
- [ ] 3.5 Run full suite: `uv run python -m pytest tests/` — no regressions in existing tests.
