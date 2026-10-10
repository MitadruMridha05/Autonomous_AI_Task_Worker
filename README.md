# OpsPilot — Autonomous AI Task Worker

OpsPilot is a small, controllable support-and-orders environment for demonstrating an agent that **acts**, handles ambiguity and failures, and verifies outcomes against backend state. It is intentionally not an ML model: the project is an agent loop plus a realistic FastAPI/SQLite application, tools, guardrails, and deterministic tests.

## Current status

**Day 2 is implemented and locally verified.** The repository currently includes:

- FastAPI + SQLite mock company app with customers, orders, invoices, refunds, notifications, HTML pages, and REST endpoints.
- Provider-neutral Anthropic and OpenAI-compatible tool-calling adapters.
- A plan/act/observe loop with structured tool schemas, bounded tool results, trace files, approval gates, clarification support, and safe finish statuses.
- Playwright browser actions that expose visible page text and interactive controls rather than raw HTML.
- Working memory, structured goal/planning helpers, backend verifier, failure classification, retryable error metadata, and an opt-in UI chaos injector.
- An optional invoice task toolset that filters invoices and exports deterministic CSV files.
- **52 automated tests** covering the app, real HTTP/SQLite agent path, provider translations, tools, approvals, browser contracts, invoice export, and chaos recovery.

Day 3 items such as MLflow/DVC evaluation orchestration, Docker images, CI workflow contents, and report charts remain intentionally deferred. Empty placeholder files for those future milestones are not treated as completed features.

## Architecture

```text
Natural-language task
        |
        v
LLM adapter -> structured tool call -> approval/validation guard
        ^                                      |
        |                                      v
trace + tool result <- API tools / browser tools / file tools
        |
        v
human clarification or finish report
        |
        v
backend verifier (REST state and persisted refund evidence)
```

The core loop is domain-agnostic. Domain behavior lives in registered tools. Risky refund, email, and browser-click actions require approval; ambiguous requests can use `ask_user`. The verifier checks application state, not the model's prose.

## Repository structure

```text
app/
  main.py, db.py, seed.py, services.py, chaos.py   Mock app and business rules
  templates/                                       Browser-facing HTML
agent/
  core/                                            LLM, loop, guard, planner, memory, verifier
  tools/                                           API, browser, file, and invoice tools
  prompts/                                         Versioned system prompts
interface/                                         Optional UI entry points
scripts/                                           Provider and offline smoke scripts
tests/                                             52 deterministic tests
runs/                                              JSON traces (ignored except .gitkeep)
```

## Prerequisites and setup

- Python 3.11+ (tested in this workspace with Python 3.12)
- A virtual environment is recommended.
- A live provider key is needed only for a real LLM run. The full automated suite uses a scripted LLM and does not require a key.

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Do not commit `.env` or provider credentials. `OPSPILOT_DB` may be set to point the app at a separate SQLite file; otherwise it uses `data/opspilot.db`.

## Run the application

Seed/reset the local database:

```bash
python -m app.seed
```

Start the mock app:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Useful endpoints:

- `GET /api/health`
- `GET /api/customers?q=Priya%20Sharma`
- `GET /api/orders?customer_id=1`
- `POST /api/orders/1004/refund` with `{"reason":"Item arrived damaged"}`
- `GET /api/invoices?overdue_days_gt=30`
- `/customers` and `/orders/1004` for the browser UI

## Run the agent

With the app running and `.env` configured:

```bash
python -m agent.cli --auto-approve \
  "Priya Sharma got a damaged item. Refund her latest order and let her know."
```

Without `--auto-approve`, the CLI asks before refunding or sending an email. The run writes a JSON trace under `runs/`. The offline plumbing smoke test needs no provider key:

```bash
python -m scripts.smoke_offline
```

The provider tool-calling check is:

```bash
python -m scripts.hello_tool_call
```

## Day 2 scenarios

1. **Normal multi-step task:** search Priya, list her newest order, inspect it, approve a refund, approve an email, and verify the order state.
2. **Invoice export:** use `build_day2_invoice_tools(...)` to list unpaid invoices overdue by more than 30 days and export them to CSV.
3. **Ambiguity:** searching `John` returns John Mathew and John D'Souza; the agent must ask instead of guessing.
4. **Failure recovery:** set `OPSPILOT_UI_REFUND_FAILURES=1`. The first HTML refund submission returns 500 while the REST API remains usable as a UI-to-API fallback. The API client marks 5xx/timeout/network failures as retryable.
5. **Idempotency:** order `1005` is already refunded; a second refund is rejected with `already_refunded` and does not create another refund record.

## Tests and validation

```bash
python -m pytest
```

The suite uses temporary SQLite databases and both FastAPI `TestClient` and a real local Uvicorn server. It verifies database state directly for the important refund workflow. Browser wrapper contracts are tested without requiring a browser download; install Playwright's browser binaries if you want to run a live browser demo:

```bash
python -m playwright install chromium
```

## Security and limitations

- The mock data is fake and the app has no authentication; it is for local demonstration only.
- The admin reset endpoint is a test helper and must not be exposed publicly.
- Browser page text is treated as untrusted data by the prompt, and extraction is limited to visible text and controls.
- Live LLM calls depend on provider credentials, model availability, quotas, and network access; deterministic tests do not.
- MLflow/DVC, Docker/Compose, CI automation, dashboards, and cloud deployment are future milestones rather than claimed Day 2 functionality.
