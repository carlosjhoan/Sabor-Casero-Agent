# Orchestration — LLM Planner with Tool Calling

## Purpose

Replace the hardcoded pipeline (`classify → domain skills → respond`) with an LLM-based Planner that treats skills as callable tools, reasons about execution order, reflects on results, and streams thinking transparently. Both old and new paths coexist behind feature flag `use_llm_planner` (default `false`).

## Requirements

### R-ORCH-01: Feature flag coexistence

The system MUST support both orchestration paths. When `use_llm_planner=false` (default), the existing hardcoded pipeline runs unchanged. When `true`, the Planner replaces `_run_orchestration_loop`.

#### Scenario: Old pipeline unchanged with flag off
- GIVEN `use_llm_planner=false`
- WHEN a user message is processed
- THEN the hardcoded pipeline (classify → domain skills → response-build) executes identically to before
- AND all existing pipeline tests pass with zero regressions

### R-ORCH-02: Planner tool-calling loop

The Planner MUST run a think→call→reflect→repeat loop. At each iteration the LLM either calls a skill tool or calls `respond` to terminate.

#### Scenario: Order intent uses three tool calls
- GIVEN a user message "quiero dos tacos"
- WHEN `use_llm_planner=true`
- THEN the Planner SHOULD call `classify` first (1 call)
- THEN call `order-flow` with the classified segments (2nd call)
- THEN call `respond` with the final answer (3rd call)
- AND the response correctly confirms the taco order
- AND total tool calls ≤ 5

### R-ORCH-03: classify is optional

The classify tool MUST be available but the Planner MAY skip it when the message intent is unambiguous from context.

#### Scenario: Menu query without classify
- GIVEN a user message "a la plancha"
- AND the previous turn established the user is asking about menu items
- WHEN the Planner determines intent from conversation context alone
- THEN it MAY skip the `classify` tool
- AND call `menu-query` directly (1 call)
- THEN call `respond` (2nd call)

### R-ORCH-04: Exact match short-circuits RAG

When `menu-query` returns exact ontology matches, the Planner SHOULD prefer those results over calling `rag-retrieve`.

#### Scenario: Exact match skips rag-retrieve
- GIVEN a user message "¿cuánto cuesta la pechuga a la plancha?"
- WHEN the Planner calls `menu-query` and it returns exact matches with confidence ≥ 0.95
- THEN the Planner MUST skip `rag-retrieve` for those items
- AND call `respond` directly with the menu-query results

### R-ORCH-05: Reflection after each tool call

The Planner MUST examine every tool result before deciding the next action. Results include success/failure, data, and error messages that inform the next step.

#### Scenario: Skill failure triggers retry
- GIVEN the Planner calls `order-flow`
- AND the tool returns an error (e.g., database timeout)
- WHEN the Planner reflects on the error result
- THEN it MAY retry the same tool (up to 2 retries per skill per message)
- OR it MAY skip the failed skill and continue with available data
- AND the final response acknowledges the degradation

### R-ORCH-06: Hard cap at 5 tool calls

The Planner MUST NOT exceed 5 tool calls per message. At the 5th call the system MUST force-terminate by calling `respond` with available data and a fallback message.

#### Scenario: Cap enforcement with fallback
- GIVEN the Planner has made 5 tool calls without calling `respond`
- WHEN the 5th tool result is received
- THEN the system MUST force `respond` with a `FALLBACK_ERROR` or best-effort response
- AND the response includes an apology for the delay

### R-ORCH-07: Chain-of-thought visibility

The Planner MUST stream its reasoning through the existing PipelineStreamer as visible thinking phases. Each tool call decision, result summary, and reflection step MUST be displayed.

#### Scenario: Thinking phases visible
- GIVEN a user message that triggers 3 tool calls
- WHEN the Planner processes the message
- THEN PipelineStreamer displays a "Planning" phase with each tool call decision
- AND a "Reflection" phase showing tool results and next-step reasoning
- AND each phase is rendered as a streamer phase (not hidden in debug logs)

### R-ORCH-08: Error resilience

Skill execution errors MUST NOT crash the pipeline. The tool result carries the error; the Planner decides to retry, skip, or fall back.

#### Scenario: Non-critical skill fails gracefully
- GIVEN the Planner calls `rag-retrieve`
- AND the tool returns an error (ChromaDB connection failure)
- WHEN the Planner reflects on the result
- THEN the pipeline MUST NOT raise an unhandled exception
- AND the Planner SHOULD fall back to `menu-query` for available data
- AND call `respond` with partial information
- AND the error is logged but the user receives a coherent response

### R-ORCH-09: Planner prompt composition

The system prompt given to the Planner MUST include: the full list of available skills (name, description, JSON schema from SKILL.md), the conversation history summary, user preferences context, and session context (order state, user ID).

#### Scenario: Prompt includes full context
- GIVEN the Planner processes a user message
- WHEN the system prompt is constructed
- THEN it MUST list all 7 skills as tools with their descriptions and schemas
- AND include the conversation summary from the previous turn
- AND include user preferences (dietary restrictions, frequent items, address)
- AND include the current order state
