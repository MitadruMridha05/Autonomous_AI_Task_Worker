# OpsPilot: an autonomous AI task worker (Day 1 prototype)

Give OpsPilot a plain-English task such as *"Priya Sharma got a damaged item. Refund her latest order and let her know."*
It works out the steps itself, uses tools against a sandbox company app, reacts to what happens, asks for
approval before risky actions, and reports what it did with evidence.

**Status: Day 1 of 4** (foundation). Implemented and tested: mock company app (REST + HTML), tool layer,
provider-neutral LLM wrapper, the act-observe-decide loop, approval gate, run traces, CLI.
Coming next (see the roadmap): browser tools, memory, verifier, retries/fallbacks, evals, MLflow/DVC, Docker, CI.

## Requirements
Python 3.10+ and an LLM API key (Anthropic, or any OpenAI-compatible provider with tool calling).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                 # Windows: copy .env.example .env   -> then add your API key
```

## Run

```bash
# 0. (optional) run the tests, no API key needed
python -m pytest

# 1. prove your LLM key can do tool calling
python -m scripts.hello_tool_call

# 2. terminal 1: start the mock company app (auto-creates and seeds data/opspilot.db)
uvicorn app.main:app --port 8000        # browse http://127.0.0.1:8000  and  http://127.0.0.1:8000/docs

# 3. terminal 2: give the agent a task
python -m agent.cli "Priya Sharma got a damaged item. Refund her latest order and let her know."
```

The agent asks `Approve this action? [y/N]` before refunds and emails (`--auto-approve` skips the prompt).
Every run saves a JSON trace in `runs/`. Reset the demo data any time: `python -m app.seed`.

No API key yet? `python -m scripts.smoke_offline` runs the whole loop over real HTTP with a scripted stand-in
for the model (this checks the plumbing only, not model intelligence).

## Architecture (Day 1)

```
app/      Mock company app: FastAPI + SQLite. REST under /api, HTML pages for the Day 2 browser tools.
          services.py holds all business rules, so UI and API can't disagree.
agent/
  core/   loop.py (act-observe-decide), llm.py (Anthropic + OpenAI-compatible adapters),
          guard.py (approval), control.py (finish / ask_user), scripted.py (test double)
  tools/  base.py + registry.py (schema, validation, error handling), api_client.py, api_tools.py
  prompts/system_v1.md   versioned system prompt
tests/    49 tests: app rules, tool layer, loop (real tools + real DB, scripted LLM), adapters, CLI over real HTTP
scripts/  hello_tool_call.py, smoke_offline.py
```

Flow: `task -> LLM picks tool call(s) -> guard (approval for risky tools) -> registry validates + executes ->
structured result (ok or classified error) -> back to the LLM -> ... -> finish(status, summary, evidence)`.

## Key design decisions
- **Own loop, no framework.** ~150 lines I can explain line by line.
- **Tools are data.** Name + Pydantic arg model + function. The same model creates the JSON schema the LLM sees and validates what it sends back. New capability = new Tool, loop unchanged.
- **Failures are observations.** Unknown tool, bad args, HTTP 404/409/5xx, crashes: all become structured results (`type`, `retryable`) the model can reason about; nothing crashes the loop.
- **Provider-neutral history.** Swapping Claude for Gemini/OpenAI/Ollama is configuration only.
- **Risky actions are gated outside the model.** The guard, not the prompt, enforces approval.
- **Safety rules live in the backend too.** The mock app itself refuses double refunds (UNIQUE constraint + 409), so a confused agent cannot corrupt data.

## Models, APIs, libraries
Default model `claude-haiku-5-5` via the Anthropic API (configurable; any OpenAI-compatible model with tool calling works).
FastAPI, Uvicorn, Jinja2, SQLite (stdlib), Pydantic, httpx, python-dotenv, pytest, `anthropic` and `openai` SDKs.

## Known limitations (Day 1)
- No independent verifier yet: the model re-reads the order and reports; Day 2 adds a backend-state verifier.
- No automatic retry/backoff or UI-to-API fallback yet (errors are classified and visible to the model).
- No browser tools, no persistent memory beyond the conversation, no clarification/ambiguity detector beyond the prompt.
- Anthropic and OpenAI-compatible adapters are unit-tested for message translation, but the live provider calls depend on your API key.

## Assumptions
Single-tenant sandbox, no login, all data fake. Refunds are full-amount and only for `delivered` orders. Emails are recorded in the database, not actually sent.
