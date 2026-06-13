# Delta for Orchestration

## ADDED Requirements

### R-ORCH-10: Six synthetic order tools replace order-flow

The Planner MUST have 6 synthetic order tools — `add-item`, `remove-item`, `update-item`, `get-order`, `confirm-order`, `cancel-order` — replacing the single `order-flow` skill. The `order-flow` skill SHALL move to `_AUTOMATIC_SKILLS` and MUST NOT appear as a callable tool. Synthetic tools SHALL follow the existing `get-full-menu` pattern: registered via `SkillToolAdapter` with name, description, JSON schema, and dispatch routing to `OrderOrchestrator` CRUD methods.

#### Scenario: Simple add-item flow replaces old order-flow call
- GIVEN a user message "quiero dos tacos"
- WHEN `use_llm_planner=true`
- THEN the Planner SHOULD call `classify` (1st call)
- THEN call `add-item` with `{item: "tacos", quantity: 2}` (2nd call)
- THEN call `respond` with confirmation (3rd call)

#### Scenario: Multi-step order with verification
- GIVEN a user message "dos tacos y una soda, luego confirmo"
- WHEN the Planner classifies the intent as order
- THEN the Planner SHOULD call `add-item` per item (calls 1–2)
- THEN call `get-order` to verify state (call 3)
- THEN call `confirm-order` (call 4)
- THEN call `respond` with summary (call 5)

### R-ORCH-11: Synthetic tool error semantics

Each synthetic tool MUST return `{success: bool, data: any, error: string | null}`. The Planner MUST reflect on errors before proceeding. Invalid items, duplicate additions, or confirm-before-items MUST produce structured errors without crashing.

#### Scenario: Invalid item rejected gracefully
- GIVEN the Planner calls `add-item` with an item not on the menu
- WHEN the tool validates against the ontology
- THEN it returns `success: false, error: "Item not found"`
- AND the Planner SHOULD NOT retry the same invalid item
- AND SHOULD inform the user the item is unavailable

#### Scenario: confirm-order with empty cart rejected
- GIVEN the Planner calls `confirm-order` with no items added
- WHEN the tool checks for existing items
- THEN it returns `success: false, error: "No items to confirm"`
- AND the Planner SHOULD guide the user to add items first

## MODIFIED Requirements

### R-ORCH-02: Planner tool-calling loop

The Planner MUST run a think→call→reflect→repeat loop. At each iteration the LLM either calls a skill tool or calls `respond` to terminate.
(Previously: described the loop with `order-flow` as an example callable tool)

#### Scenario: Order intent uses granular tools (replaces old order-flow scenario)
- GIVEN a user message "quiero dos tacos"
- WHEN `use_llm_planner=true`
- THEN the Planner SHOULD call `classify` first (1 call)
- THEN call `add-item` with the parsed item and quantity (2nd call)
- THEN call `respond` with the confirmation (3rd call)
- AND the response correctly confirms the taco order
- AND total tool calls ≤ 5

### R-ORCH-05: Reflection after each tool call

The Planner MUST examine every tool result before deciding the next action. Results include success/failure, data, and error messages that inform the next step.
(Previously: referenced `order-flow` as the failing tool example)

#### Scenario: Synthetic tool failure triggers retry
- GIVEN the Planner calls `add-item`
- AND the tool returns an error (e.g., database timeout)
- WHEN the Planner reflects on the error result
- THEN it MAY retry the same tool (up to 2 retries per tool per message)
- OR it MAY skip the failed tool and continue with available data
- AND the final response acknowledges the degradation

### R-ORCH-09: Planner prompt composition

The system prompt given to the Planner MUST include: the full list of available tools (name, description, JSON schema), the conversation history summary, user preferences context, and session context (order state, user ID).
(Previously: referenced "7 skills" — tool count changes as order-flow is replaced by 6 granular tools)

#### Scenario: Prompt includes extended tool list
- GIVEN the Planner processes a user message
- WHEN the system prompt is constructed
- THEN it MUST list all available tools with their descriptions and schemas
- AND MUST include the 6 synthetic order tools (`add-item`, `remove-item`, `update-item`, `get-order`, `confirm-order`, `cancel-order`)
- AND MUST NOT include `order-flow` as a callable tool
- AND MUST include the conversation summary from the previous turn
- AND MUST include user preferences (dietary restrictions, frequent items, address)
- AND MUST include the current order state
