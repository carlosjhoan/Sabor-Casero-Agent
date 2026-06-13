# AGENTS.md

## Repository overview

This is the companion repository for Edward Donner's "Master AI Agentic Engineering" course. Six weeks of labs plus one standalone capstone-style project (`sabor_casero_assistant/`).

| Directory | Framework |
|---|---|
| `1_foundations/` | Python foundations + Sabor Casero prototype (notebooks) |
| `2_openai/` | OpenAI Agents SDK |
| `3_crew/` | CrewAI |
| `4_langgraph/` | LangGraph |
| `5_autogen/` | AutoGen |
| `6_mcp/` | MCP (Model Context Protocol) |
| `sabor_casero_assistant/` | **Standalone project** — restaurant assistant "Luz Stella" |

## Active project: `sabor_casero_assistant/`

A multi-stage LLM pipeline for a Mexican restaurant order assistant. Gradio UI.

### Setup

- Python 3.12, `uv` for package management
- Copy `.env.example` → `.env`, fill in at least `DEEPSEEK_API_KEY`
- Run: `python src/main.py --mode gradio` (serves on port 7860)
- CLI mode: `python src/main.py --mode cli`

### Architecture

Clean Architecture with three layers: **domain** / **application** / **infrastructure**.

```
src/
  main.py                       # entry point
  config/environment.py         # pydantic-settings singleton (reads .env)
  config/config.py              # legacy AppConfig singleton (avoid, use environment.py)
  utils/config.py               # legacy YAML loader (avoid, use environment.py)
  infrastructure/
    llm_client.py               # Abstract base + provider factory
    providers/                  # deepseek, openai, anthropic, gemini, groq, minimax
  ui/gradio_app.py              # Gradio 6.x chat interface
  core/
    assistant.py                # Main pipeline orchestrator
    classifier/                 # HybridClassifier (rule + LLM), StructuredConversationManager
    order/                      # Order domain (domain/application/infrastructure layers)
    response/                   # ResponseBuilder (hybrid: structured components + LLM)
    extractor/                  # RAG retriever (vector_db via ChromaDB, or LLM-only)
    memory/                     # Context summarizer (JSON persistence)
    conversation_log/           # Interaction logging (JSON persistence)
    knowledge/registry.py       # Knowledge registry
```

### Pipeline (per message)

1. **Classification** — HybridClassifier (rule-based + LLM) identifies intent and topics
2. **RAG retrieval** — Conditionally fetches menu/info from ChromaDB vector store
3. **Order processing** — OrderOrchestrator + ActionPlanner handles order mutations
4. **Response generation** — ResponseBuilder blends order state + RAG results + brand voice via LLM
5. **Summarization** — Fire-and-forget background task writes conversation summary to JSON

### Key resources

| Resource | Path |
|---|---|
| Prompts | `prompts/classifier_intent/`, `prompts/response/`, `prompts/action_planner/`, etc. |
| Documents (RAG source) | `data/documents/` |
| Orders & sessions (JSON) | `data/orders/`, `data/persistence/sessions.json` |
| Brand voice template | `data/templates/brand_templates.json` |

### LLM routing

Each pipeline stage can use a different provider/model via `.env`:
```
LLM_PROVIDER_CLASSIFIER=deepseek
LLM_MODEL_CLASSIFIER=deepseek-chat
LLM_PROVIDER_RESPONSE=deepseek
```
Supported providers: `deepseek` (default), `openai`, `anthropic`, `gemini`, `groq`, `minimax`.

### Conventions

- Code comments in **Spanish**, identifiers in **English**
- Classes: PascalCase, functions/variables: snake_case
- Docstrings: Google style in Spanish
- Two config systems exist: prefer `src/config/environment.py` (pydantic-settings). The YAML/`AppConfig` paths are legacy.
- `sys.path.append` is used in `main.py` to resolve imports — don't remove it
- Conversation state managed in `JSON` files, NOT in-memory — state persists across restarts

### Tests

- `tests/` directory exists but is **empty** — no test framework is set up yet
- `test_tools/` has one-off scripts (e.g., `simple_vector_retriever.py`)

### Dev notes

- Note that the `project_manager/` directory at the project root contains session context and task-tracking scripts (`update_task.py`, `session_report.py`) — these are custom workflow tools, not part of the assistant runtime.
