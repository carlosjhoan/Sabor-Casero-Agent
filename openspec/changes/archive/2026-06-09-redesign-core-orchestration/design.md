# Design: Redesign Core Orchestration — Pipeline → LLM Planner with Tool Calling

## Technical Approach

Replace the hardcoded pipeline in `Assistant._run_orchestration_loop()` with a `Planner` class that uses the LLM's tool-calling capability to decide which skills to invoke, in what order, and whether to retry/skip on failure. Each of the 7 skills becomes a tool via a `SkillToolAdapter`. The Planner loops: think → call tool → reflect → repeat, capped at 5 calls, then terminates via the `respond` tool. The old pipeline is preserved behind feature flag `use_llm_planner` (default `False`).

## Architecture Decisions

| Decision | Choice | Alternatives | Rationale |
|----------|--------|-------------|-----------|
| Planner stateless per message | New `Planner` instance per call | Reusable planner with accumulated state | Stateless avoids cross-message contamination, simplifies error recovery |
| `respond` as a synthetic tool | Built-in tool at planner level | Letting planner return text | Consistent with tool-calling loop — every output goes through the same mechanism |
| Prompt in `prompts/planner/` file | Single text file per existing pattern | Langfuse-hosted prompt | Matches existing convention (all prompts are `.txt` files) |
| Classify as optional tool | First-class tool in registry | Hardcoded mandatory call | Planner calls classify only when intent is ambiguous |
| Tool errors returned inline | Error string in tool result | Exception propagation | LLM can decide retry/skip, no crashes |

## Data Flow

```
User message
    │
    ▼
Assistant._run_orchestration_loop()
    │
    ├── use_llm_planner=False  →  [existing hardcoded pipeline]
    │
    └── use_llm_planner=True   →  Planner.run()
                                      │
                               ┌──────┴──────┐
                               │  Think Phase │  LLM decides next tool call
                               └──────┬──────┘
                                      │ tool name + args
                                      ▼
                               ┌──────────────┐
                               │ Tool Adapter │  SkillToolAdapter.execute()
                               │              │  maps tool_call → skill.execute()
                               │              │  returns SkillResult as JSON
                               └──────┬──────┘
                                      │ result
                                      ▼
                               ┌──────────────┐
                               │ Reflect Phase│  Result fed back to LLM
                               │              │  LLM decides:
                               │              │   - another tool
                               │              │   - respond (terminate)
                               └──────┬──────┘
                                      │ respond(name="respond", arguments={text: ...})
                                      ▼
                               ┌──────────────┐
                               │  Termination │  response_text extracted
                               └──────────────┘
                                      │
                                      ▼
                              Final response dict
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/core/agent/planner.py` | Create | `Planner` class: state machine, LLM loop, tool dispatch, respond built-in |
| `src/core/agent/skill_tools.py` | Create | `SkillToolAdapter`: `list_tools() → list[dict]`, `execute_tool(name, args) → dict` |
| `src/core/assistant.py` | Modify | `_run_orchestration_loop` forks on `use_llm_planner` flag |
| `src/config/environment.py` | Modify | Add `use_llm_planner: bool = False` feature flag |
| `prompts/planner/system_prompt.txt` | Create | System prompt with skill registry context, termination rules, reflection instructions |
| `tests/agent/test_planner.py` | Create | Planner unit tests (loop, tool selection, termination) |
| `tests/agent/test_skill_tools.py` | Create | Tool adapter unit tests |

## Interfaces / Contracts

### Planner state machine

```python
from enum import Enum

class PlannerState(str, Enum):
    THINKING = "thinking"      # LLM deciding next action
    EXECUTING = "executing"    # Running a tool
    REFLECTING = "reflecting"  # Feeding result back to LLM
    TERMINATED = "terminated"  # respond called or cap reached

class Planner:
    def __init__(self, llm_client, skill_registry, orchestrator, streamer, settings):
        self.state = PlannerState.THINKING
        self.tool_call_count = 0
        self.max_tool_calls = 5
        self.tool_timeout = 30.0  # seconds per tool call

    async def run(self, user_message: str, session_ctx: SessionContext,
                  trace_id: str) -> Dict[str, Any]:
        """
        Main loop: think → execute → reflect → repeat/terminate.
        Returns {"response": str, ...} matching the current pipeline contract.
        """
```

### Tool adapter

```python
class SkillToolAdapter:
    @staticmethod
    def list_tools(registry: SkillRegistry) -> list[dict]:
        """Build OpenAI-compatible tool definitions from all SKILL.md frontmatter."""
        # Returns list of:
        #   {
        #       "type": "function",
        #       "function": {
        #           "name": skill.name,
        #           "description": skill.trigger,
        #           "parameters": {"type": "object", ...}
        #       }
        #   }

    async def execute_tool(self, tool_name: str, arguments: dict,
                           context: dict) -> dict:
        """Execute a skill by name and return its result as a JSON-serializable dict."""
        # Returns {"success": bool, "result": ...} on ok,
        # or {"success": False, "error": "..."} on failure
```

### `respond` tool schema

```json
{
    "name": "respond",
    "description": "Provide the final response to the user. Call this only when you have gathered all needed information.",
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The final assistant response"}
        },
        "required": ["text"]
    }
}
```

## Prompt Structure

`prompts/planner/system_prompt.txt`:

```
Eres Luz Stella, asistente del restaurante Sabor Casero.
Dispones de las siguientes herramientas:

{skill_descriptions — generated from registry.list_skills()}

Reglas:
1. Cada mensaje del usuario, piensa qué herramientas necesitas.
2. Puedes llamar varias herramientas, una por vez.
3. Después de cada resultado, reflexiona si necesitas más información.
4. Llama "classify" solo si el mensaje es ambiguo.
5. Cuando tengas la respuesta final, llama "respond".
6. Máximo {max_tool_calls} llamadas por mensaje.
7. Si una herramienta falla, intenta con otra o responde con disculpa.

Contexto de conversación:
{resumen de conversación}

Pedido actual:
{resumen del pedido}
```

The prompt is loaded from file and populated at runtime with skill descriptions, conversation summary, and order summary — same pattern as existing prompts.

## Streamer Integration

Each Planner phase emits a visible step:

- **Think phase** → `streamer.phase("Planning", emoji="🧠")`: shows tool name + reasoning
- **Execute phase** → `streamer.phase(f"Skill: {tool_name}", emoji="⚙️")`: wraps each skill execution; calls `.done()` with result summary
- **Failure phase** → `streamer.phase("Fallback", emoji="⚠️")`: on tool error or cap reached

When `respond` is called, the streamer prints the final response via `streamer.response()`.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Tool timeout (30s) | TimeoutError returned as tool result `{"success": false, "error": "timeout"}` |
| Skill execution error | SkillResult.error serialized to tool result string |
| 5 calls exhausted without `respond` | Planner forces `FALLBACK_ERROR` response |
| LLM output not parseable | Retry LLM call once; if still fails, respond with apology |
| `respond` called with empty text | Substitute `FALLBACK_ERROR` |

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `Planner` loop with mock LLM returning tool calls | Fake `chat_completion` returns controlled dicts; verify correct dispatch |
| Unit | `SkillToolAdapter.list_tools()` | Assert 7 tool definitions, correct names/descriptions from SKILL.md |
| Unit | `Planner` termination (cap reached, respond called) | Forced tool_call_count==5; verify respond without LLM retry |
| Unit | Tool timeout handling | Mock skill.execute to sleep >30s; verify error result |
| Integration | Planner + real SkillOrchestrator | Load 1–2 skills (classify, response-build), verify end-to-end flow |
| Regression | Old pipeline with `use_llm_planner=False` | Existing tests pass unchanged |

## Migration / Rollout

No migration required. Feature flag `use_llm_planner` defaults to `False` — the old pipeline runs untouched. When the flag is enabled, the new Planner path activates. Rollback: toggle flag back to `False`, delete `planner.py` and `skill_tools.py` if desired.

## Open Questions

- [ ] Tool parameter JSON schemas — each skill's SKILL.md has a "Contract" section with input/output descriptions, but not machine-parseable JSON Schema. Should we add a `schema` field to frontmatter or derive schemas from existing Pydantic models?
