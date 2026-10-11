# Day 3 and Day 4 completion report

## Initial audit

Day 1–2 functionality was already implemented: FastAPI/SQLite mock app, API and browser tools, tool registry and validation, approval policy, clarification control, provider adapters, scripted loop tests, invoice export, failure classification, and verifier utilities. The original Day 3–4 placeholders were empty: evaluation runner/report, DVC and params files, Docker files, CI workflow, and Day 4 submission documentation.

## README requirements addressed

- Day 3: 8–10 evaluation tasks including failure injection and ambiguity; MLflow run logging; DVC data/pipeline versioning; Pandas/Seaborn reporting; pytest tests; Dockerfiles/Compose; GitHub Actions CI.
- Day 4: architecture/design/setup/assumptions/limitations documentation and a reproducible demo script covering normal execution, recovery, clarification, approval, and verification. A screen recording itself was not created because this coding environment has no interactive recording tool.

## Implementation

- `evals/tasks/day3_tasks.yaml`: 9 scenarios.
- `evals/run_evals.py`: real HTTP/SQLite evaluation harness, ground-truth checks, JSON artifacts, MLflow SQLite tracking, and safe fallback when MLflow is unavailable.
- `evals/report.py`: Pandas summary plus Seaborn/Matplotlib chart.
- `tests/test_evals.py`: task manifest, real HTTP harness, and report regression tests.
- `dvc.yaml` and `params.yaml`: `seed_db → run_evals → report` pipeline.
- `docker/Dockerfile` and `docker/docker-compose.yml`: app and agent services.
- `.github/workflows/ci.yml`: imports, pytest, evals, and report.
- `docs/demo-script.md`, `scripts/demo_offline.py`, and README: Day 4 usage and recording guidance.
- `requirements.txt` and `.gitignore`: evaluation dependencies and generated-artifact handling.

## Test and execution evidence

- `pytest -q`: **59 passed**, one non-failing MLflow deprecation warning.
- `python -m evals.run_evals --output runs/eval_results.json`: **9/9 passed**.
- `python -m evals.report --results runs/eval_results.json --output-dir runs/report`: report and 896×672 PNG chart generated.
- `python -m compileall -q app agent evals interface scripts tests`: passed.
- Import check for app, agent CLI, eval harness, and report: passed.
- YAML parse check for task data, DVC, params, Compose, and CI: passed.
- Actual documented startup: `uvicorn app.main:app --host 127.0.0.1 --port 8765`; `/api/health` returned `{"status":"ok"}`.
- Docker image build was not run because the Docker CLI is unavailable in the sandbox. Live LLM calls were not run because the deterministic suite intentionally uses scripted model responses and no provider credential is needed.

## Remaining issues

- The Day 4 screen recording remains a manual step; the copy-paste-ready script is included.
- Hosted MLflow, Docker, DVC, browser live execution, and live provider calls require their respective external tools/services/configuration.
- Grafana/AWS stretch scope was not implemented.

## Git

- Branch: `day3-day4-reliability-polish`
- Commit message: `Complete Day 3 evaluation and Day 4 polish` (the final hash is reported in the handoff)
- Push: not performed, per instruction not to make externally visible GitHub changes without authorization.
