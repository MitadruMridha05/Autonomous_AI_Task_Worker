# Approach Guide: Autonomous AI Task Worker (deadline 12 Oct, 4 days left)

## 1. How to read this assignment

They are not asking for an ML model. They want a working **agent system**: it takes a plain-English task, acts on a real (simulated) environment, handles failures, and **proves** the outcome. Your MLOps background is a good fit because evaluation, tracking and reproducibility are what make agents reliable.

**Golden rule from the brief:** one narrow task domain that genuinely works beats a broad system with mocked parts. So build:

- one **mock company app** that you own and control
- one **agent** that works on any task in that app, not hard-coded flows
- an **evaluation suite** that proves it works (this is where your MLflow/DVC skills pay off)

## 2. Project concept: "OpsPilot"

**Mock app:** a small support and orders admin portal (customers, orders, invoices, refunds) built with FastAPI + SQLite and simple HTML pages, so a browser agent can click through it. It also exposes a REST API.

**Example tasks the same agent must handle (this demonstrates generalization):**

| Task | What it tests |
|---|---|
| "Priya Sharma got a damaged item. Refund her latest order and let her know." | Multi-step planning, memory, approval before refund, verification |
| "Export all invoices overdue by more than 30 days to a CSV." | File tool, filtering, different tool mix |
| "Refund John's order." (two Johns exist) | Ask for clarification instead of guessing |
| Refund button fails with a 500 on first try | Failure detection, retry, UI→API fallback |
| Order already refunded | Verify first, report "no action needed" |

## 3. Architecture (your "pipeline")

Like your House Price Predictor (ingestion → transformation → training → evaluation → artifacts), the agent is a pipeline:

```
Task (natural language)
   ↓
1. UNDERSTAND  → goal + success criteria (structured JSON via Pydantic)
   ↓
2. PLAN        → list of steps (re-planned when things change)
   ↓
┌─►3. ACT      → call a tool (browser / API / files)
│  4. OBSERVE  → result, page text, errors
│  5. REMEMBER → store discovered facts (customer_id, order_id…)
│  6. DECIDE   → next action / retry / alternative / ask user
└──────┘
   ↓
7. VERIFY      → check ground truth in DB/API against success criteria
   ↓
8. REPORT      → summary + evidence (action trace, screenshots, state diff)
```

**Key components**

- **LLM wrapper:** one interface, swappable provider.
- **Tool registry:** each tool has a name, a JSON schema and a function. Adding a tool changes no core code. This is your generalization story.
- **Memory:** a working-memory dict plus a run log.
- **Guard / approval gate:** actions tagged `risky` (refund, delete, send email) pause for human approval. Ambiguity triggers a clarification question.
- **Failure handler:** error types are classified (transient, not found, permission, no-op) and each gets a different response. Loop detection and a max-step limit stop it from running forever.
- **Verifier:** checks the **backend state**, not the LLM's claim. For example, it queries `GET /orders/1042` and confirms `status == "refunded"` and that a refund record exists. This is your biggest differentiator.

## 4. Your resume tools → where to use them

| Resume skill | Use in this project |
|---|---|
| **Python** | Everything |
| **SQL** | SQLite DB for the mock app, plus a run-history table |
| **Pandas / NumPy** | Analyse eval results (success rate, steps per task, retries) |
| **Matplotlib / Seaborn** | Charts for the README (success rate per task, steps/latency) |
| **MLflow** | Log every agent run: params (model, prompt version, task ID), metrics (success, steps, retries, tokens, latency), artifacts (trace JSON, screenshots) |
| **DVC** | Version the eval task set and run results; define a pipeline in `dvc.yaml` (`seed_db → run_evals → report`) |
| **Docker** | `docker-compose` with two containers: mock app and agent |
| **CI/CD (GitHub Actions)** | On each push: lint, unit tests, and a small eval run with a mocked LLM |
| **Git / Linux** | Version control, shell scripts |
| **Joblib** | Cache LLM responses and tool outputs for fast deterministic tests |
| **Grafana** | *Stretch:* dashboard of success rate and failures over runs |
| **AWS** | *Stretch:* host the demo on EC2 |
| **Scikit-learn / TensorFlow / NLP** | Not needed. Don't force them. Honesty here will serve you better in the technical discussion. |

Note that the brief's evaluation criteria (Reliability, Verification, Engineering Quality) reward the MLOps layer, but only if the core agent works first.

## 5. Tools and concepts NOT on your resume (learn these)

**Tools**

| Tool | Why |
|---|---|
| **LLM API with tool/function calling** (Anthropic Claude, OpenAI, or Gemini free tier) | The agent's brain. Pick one and wrap it. |
| **Pydantic** | Structured outputs (plan, goal, verification result) |
| **FastAPI** + **Jinja2** | Mock company app and its API |
| **Playwright (Python)** | Browser automation, screenshots, page text |
| **Tenacity** (or a hand-written retry) | Retry with backoff |
| **pytest** | Unit tests for tools, verifier, guard |
| **Streamlit** or a CLI | Interface for approvals and showing the trace |
| **Docker Compose** | Running multiple services |
| **A screen recorder (OBS / Loom)** | Demo video |

**Concepts**

1. Agent loop: ReAct and plan-and-execute
2. Function/tool calling and JSON schemas
3. Structured outputs and validation
4. Context management: truncating page content so it fits the prompt
5. Error taxonomy, retries and **idempotency** (don't refund twice on a retry)
6. Post-condition verification (checking ground truth)
7. Human-in-the-loop, permissions and guardrails
8. Prompt injection basics (a webpage's text must not be treated as instructions)
9. Agent evaluation: success rate, steps, cost, failure-injection tests
10. Observability: structured logs and traces

**Recommendation:** write the loop yourself instead of using LangChain/LangGraph. You must explain and modify it in the technical discussion, and a 200-line loop you understand beats a framework you don't.

## 6. Repository structure

```
opspilot/
├── app/                      # Mock company app
│   ├── main.py               # FastAPI routes (HTML + REST)
│   ├── db.py, seed.py        # SQLite schema + seed data
│   ├── templates/            # login, customers, orders, refund form
│   └── chaos.py              # failure injection (flaky 500s, renamed buttons)
├── agent/
│   ├── core/
│   │   ├── loop.py           # main act-observe-decide loop
│   │   ├── planner.py        # goal parsing + plan/re-plan
│   │   ├── verifier.py       # ground-truth checks
│   │   ├── memory.py
│   │   ├── guard.py          # approval + clarification gate
│   │   ├── failures.py       # error classification, retry, fallback
│   │   └── llm.py            # provider wrapper
│   ├── tools/
│   │   ├── base.py, registry.py
│   │   ├── browser.py        # Playwright tools
│   │   ├── api.py            # HTTP tools for the mock app
│   │   └── files.py          # CSV/read/write
│   ├── schemas.py            # Pydantic models
│   └── prompts/              # versioned prompts
├── interface/                # cli.py or streamlit_app.py
├── evals/
│   ├── tasks/*.yaml          # task + expected end state + injected faults
│   ├── run_evals.py          # runs tasks, logs to MLflow
│   └── report.py             # Pandas + Seaborn charts
├── tests/
├── dvc.yaml, params.yaml     # seed_db → run_evals → report
├── docker/                   # Dockerfiles + docker-compose.yml
├── .github/workflows/ci.yml
├── monitoring/               # Grafana (stretch)
└── README.md                 # setup, architecture, decisions, limitations
```

## 7. Four-day roadmap

**Day 1 (Thu 8 Oct): Foundation**
- Create the repo, set up the environment, pick the LLM provider, make a first successful tool-calling request.
- Build the mock app (customers, orders, refund flow, REST API) and seed data.
- Write the API tools and a minimal loop that completes **Task 1** end-to-end.

**Day 2 (Fri 9 Oct): Make it an agent**
- Add Playwright browser tools.
- Add goal and success-criteria extraction, memory, and re-planning.
- Add the verifier, the failure handler (retry plus UI→API fallback) and the approval/clarification gate.
- Get Tasks 2, 3 and 4 working.

**Day 3 (Sat 10 Oct): Reliability and MLOps layer**
- Build the eval harness with 8–10 tasks, including failure-injection and ambiguous cases.
- Log runs to MLflow, version the eval data with DVC, and plot results with Pandas/Seaborn.
- Write pytest tests, the Dockerfiles and compose file, and the GitHub Actions CI.

**Day 4 (Sun 11 Oct): Polish and submission material**
- Write the README with architecture, design decisions, assumptions, models/APIs used, known limitations and what you'd build next.
- Record a 3–5 minute demo: a normal task, a failure with recovery, a clarification question, an approval, and the verification output.
- Stretch only if time remains: Grafana or AWS.

**Mon 12 Oct:** buffer. Re-run the demo from a clean clone and submit early.

## 8. Cut order if time runs short

1. **Must have:** the loop, API + browser tools, verifier, retry/fallback, approval gate, 5+ evals, README, demo video
2. **Should have:** MLflow logging, DVC pipeline, Docker, CI
3. **Stretch:** Grafana, AWS, Streamlit UI polish, parallel tasks

## 9. Design decisions to be ready to defend

- **Own loop vs a framework:** control, debuggability, and you can explain every line.
- **Verifier checks the database, not the LLM's claim:** agents often say "done" when they aren't.
- **Hybrid UI + API tools:** the browser covers the realistic path, and the API is a reliable fallback.
- **Risky-action approval:** safety and trust in an enterprise setting.
- **Eval suite with injected failures:** reliability is measured, not assumed.
- **Prompts and tasks versioned (Git/DVC) and runs tracked (MLflow):** reproducibility.

## 10. Common pitfalls

- Spending Day 3 on Grafana and AWS while the agent still breaks on edge cases
- Mocking the verifier or the failures. Make them real, since the brief explicitly warns against "mostly mocked" functionality.
- Hard-coding task steps. If you can't swap in a new task without touching core code, generalization scores low.
- Dumping full HTML into the prompt. Extract visible text and interactive elements only.
- Retrying non-idempotent actions blindly


## 11. Day 3–4 implementation delivered

The Day 3 reliability/MLOps layer is implemented and integrated with the existing Day 1–2 app and agent:

- `evals/tasks/day3_tasks.yaml` contains **9 deterministic scenarios**: normal refund/email, invoice CSV export, ambiguous identity, already-refunded no-op, non-refundable order, injected UI failure with API recovery, approval denial, malformed arguments, and execution-limit termination.
- `evals/run_evals.py` runs the real FastAPI app over HTTP, the real SQLite-backed tools and agent loop, and scripted model turns. It writes JSON results, ground-truth checks state through the API, and logs to MLflow when available using `runs/mlflow.db` (JSON results remain the source of truth if tracking is unavailable).
- `evals/report.py` uses Pandas and Seaborn/Matplotlib to produce `runs/report/report.md` and `runs/report/task_results.png`.
- `dvc.yaml` defines `seed_db → run_evals → report`; `params.yaml` records the task file and execution parameters.
- `docker/Dockerfile` and `docker/docker-compose.yml` define the mock app and evaluation services.
- `.github/workflows/ci.yml` checks imports, runs pytest, executes the deterministic evaluation suite, and builds the report.

Day 4 submission material is documented in [`docs/demo-script.md`](docs/demo-script.md). It includes the normal task, recovery, clarification, approval, verification, and evaluation-report scenes. A real screen recording is intentionally not committed by this coding run; the script is copy-paste-ready for recording.

## 12. Setup and commands

### Linux/macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env                 # add a provider key only for live LLM runs
pytest -q
python -m evals.run_evals
python -m evals.report
uvicorn app.main:app --reload --port 8000
```

### Windows PowerShell

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
pytest -q
python -m evals.run_evals
python -m evals.report
uvicorn app.main:app --reload --port 8000
```

For a live task, start the app in one terminal and run, for example:

```bash
python -m agent.cli --auto-approve "Priya Sharma got a damaged item. Refund her latest order and let her know."
```

Without an LLM credential, use the offline deterministic evaluation command. It uses a local database and scripted model responses; it does not send real email or make external changes.

### Docker and DVC

```bash
cd docker
 docker compose up --build app
# In another terminal from the repository root:
python -m evals.run_evals && python -m evals.report
# If DVC is installed:
dvc repro
```

Docker configuration was syntax-validated in this environment, but the Docker executable itself was not available for an image build. Live provider integration was not run because no provider credential was required for, or used by, the deterministic suite.

## 13. Verified results and known limitations

Latest local verification:

- `pytest -q`: **59 passed**.
- `python -m evals.run_evals`: **9/9 passed**.
- `python -m evals.report`: report and PNG chart created successfully.
- Python compile/import checks: passed.
- YAML parsing for task, DVC, Compose, and CI files: passed.

Known limitations: MLflow is configured for a local SQLite tracking store rather than a hosted tracking server; Docker and DVC commands require those tools to be installed; browser-agent live execution and real LLM calls require the configured provider/browser dependencies and credentials. No Grafana/AWS stretch work is included.

## 14. Day 3–4 completion checklist

| Requirement | Status | Evidence |
|---|---|---|
| 8–10 task evaluation harness with failure/ambiguous cases | PASS | 9 tasks in `evals/tasks/day3_tasks.yaml`; 9/9 run |
| MLflow run logging | PASS | Local SQLite MLflow store created by `run_evals` |
| DVC versioned pipeline | PASS | `dvc.yaml`, `params.yaml`, task manifest |
| Pandas/Seaborn result plots | PASS | `evals/report.py`, generated Markdown and PNG |
| Pytest coverage | PASS | 59 tests passed, including `tests/test_evals.py` |
| Dockerfiles and Compose | PASS | Configuration written and YAML parsed; image build not run because Docker CLI is unavailable |
| GitHub Actions CI | PASS | `.github/workflows/ci.yml` written and YAML parsed |
| README architecture/setup/design/limitations | PASS | This README and `docs/demo-script.md` |
| Demo recording | BLOCKED | Recording requires an interactive recording tool; reproducible script provided |
