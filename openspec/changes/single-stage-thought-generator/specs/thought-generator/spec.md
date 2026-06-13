# Delta: Thought Generator — Single-Stage Structured Output

## Scope

Refactor `ThoughtGenerator.generate_thought()` from a two-stage LLM flow (text → ambiguity extraction) to a single-stage structured output flow using `ThoughtOutput`. Contract to `Orchestrator` and `AmbiguityResolver` unchanged — same dict keys, same types.

## ADDED Requirements

### Requirement: Single-Stage LLM Call

The `ThoughtGenerator` MUST produce `reasoning` + `ambiguity` from exactly **one** LLM call per invocation, using `response_format={"type": "json_object"}` with `output_format=ThoughtOutput`.

#### Scenario: Happy path — structured output succeeds

- GIVEN a valid `ordering_segments`, `session_id`, and optional `summary_conversation`
- WHEN `generate_thought()` calls the LLM with `response_format="json_object"` + `output_format=ThoughtOutput`
- THEN the LLM returns valid JSON matching `ThoughtOutput` schema
- AND `thought_result["thought"]` equals `ThoughtOutput.reasoning` (clean str, not JSON blob)
- AND `thought_result["ambiguity"]` is an `AmbiguityDeclaration` instance

#### Scenario: Fallback — structured output parse failure

- GIVEN the LLM response is not valid JSON or does not match `ThoughtOutput`
- WHEN `generate_thought()` attempts to parse the response
- THEN it SHALL return `success=False`, `thought=None`, `ambiguity=None`
- AND it SHALL NOT raise an unhandled exception

#### Scenario: Fallback — AmbiguityDeclaration creation failure

- GIVEN the LLM returns valid JSON with `reasoning` but `ambiguity` cannot be parsed as `AmbiguityDeclaration`
- WHEN `generate_thought()` attempts to construct the return dict
- THEN it SHALL return `ambiguity=AmbiguityDeclaration(has_ambiguity=False)` (safe default)
- AND `thought_result["thought"]` SHALL still contain the valid `reasoning` text

### Requirement: `deepseek-v4-flash` as Default Model

The `Settings.llm_model_thought_generator` default SHALL be `"deepseek-v4-flash"` for improved cost, speed, and structured-output fidelity.

#### Scenario: Default model resolves to deepseek-v4-flash

- GIVEN no `LLM_MODEL_THOUGHT_GENERATOR` env var is set
- WHEN `Settings().llm_model_thought_generator` is accessed
- THEN it MUST equal `"deepseek-v4-flash"`

## MODIFIED Requirements

### Requirement: `generate_thought()` output keys remain identical

The method MUST return a `Dict` with keys `success`, `thought`, `ambiguity`, `context`, `error` — same as before.
(Previously: returned dict with same keys from two-stage flow.)

#### Scenario: Success return contract unchanged

- GIVEN a successful invocation
- THEN the returned dict MUST contain `"thought": str`, `"ambiguity": AmbiguityDeclaration`, `"context": dict`, `"success": True`
- AND `"thought"` MUST be a plain string (not JSON)

#### Scenario: Error return contract unchanged

- GIVEN an LLM failure or parse error
- THEN the returned dict MUST contain `"success": False`, `"thought": None`, `"ambiguity": None`

### Requirement: Orchestrator consumption unchanged

`OrderOrchestrator.process_order_intent()` MUST continue reading `thought_result["thought"]` and pass it to `ActionPlanner`.
(Previously: same consumption pattern — no change in orchestrator logic.)

#### Scenario: Thought is clean reasoning text

- GIVEN the single-stage flow returns `thought_result["thought"]`
- WHEN the orchestrator passes it to `action_planner.plan_actions(thought=...)`
- THEN the value MUST be a plain string (e.g., `"El usuario quiere..."`) — never a JSON blob

#### Scenario: Ambiguity forwarded to AmbiguityResolver

- GIVEN the single-stage flow returns `thought_result["ambiguity"]`
- WHEN the orchestrator passes it to `ambiguity_resolver.resolve(ambiguity_declaration=...)`
- THEN the value MUST be an `AmbiguityDeclaration` instance (same type as before)

## REMOVED Requirements

### Requirement: `_extract_ambiguity()` method

(Reason: Ambiguity extraction is now part of the single structured LLM call — no second call needed.)

### Requirement: `_generate_thought_with_retry()` standalone stage

(Reason: Replaced by single `generate_thought()` that integrates retry logic directly around the structured output call.)

## Test Coverage

### Requirement: New tests for single-stage flow

A new test file `tests/order/test_thought_generator.py` MUST cover:

#### Scenario: Structured output returns valid ThoughtOutput

- GIVEN a mock LLM client that returns valid `ThoughtOutput` JSON
- WHEN `generate_thought()` is called
- THEN `thought_result["thought"]` is `.reasoning` and `thought_result["ambiguity"]` is `.ambiguity`

#### Scenario: AmbiguityDeclaration-safe-default on failure

- GIVEN a mock LLM that returns text NOT matching `ThoughtOutput`
- WHEN `generate_thought()` is called
- THEN `thought_result["ambiguity"]` has `has_ambiguity=False` and `thought_result["success"]` is `True` if `reasoning` was recovered, else `False`

#### Scenario: No ambiguity in output

- GIVEN `ThoughtOutput` with `ambiguity.has_ambiguity=False`
- WHEN `generate_thought()` returns
- THEN `thought_result["ambiguity"].has_ambiguity` is `False`

#### Scenario: Clean reasoning (no JSON blob)

- GIVEN `ThoughtOutput.reasoning` = `"El usuario quiere pechuga a la plancha mini."`
- WHEN `generate_thought()` returns
- THEN `thought_result["thought"]` does NOT contain `{` or `"` JSON artifacts

#### Scenario: Exactly one LLM call per invocation

- GIVEN a mocked `LLMClient.chat_completion`
- WHEN `generate_thought()` is called once
- THEN `chat_completion` is awaited exactly **once**

### Requirement: Existing tests remain passing

All tests in `tests/order/test_thought_output.py` and `tests/order/test_ambiguity_resolver.py` MUST continue passing without modification.
