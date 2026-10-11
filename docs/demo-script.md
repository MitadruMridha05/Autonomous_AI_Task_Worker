# OpsPilot Day 4 demo script

The repository includes a safe deterministic evaluation runner so the demo can be repeated without exposing an API key. For a 3–5 minute recording:

1. Start the app: `uvicorn app.main:app --reload --port 8000`.
2. Show a normal refund task with `python -m agent.cli --auto-approve ...` using a configured LLM, or show the offline suite when no credentials are available.
3. Set `OPSPILOT_UI_REFUND_FAILURES=1` and demonstrate that the API path remains available as recovery.
4. Show the ambiguous John task and the clarification question; do not guess.
5. Run the approval path once with default interactive mode and once with `--auto-approve`.
6. Show the verification evidence and database-backed order status.
7. Run `python -m evals.run_evals && python -m evals.report` and show the 9-task result table/chart.

The offline command is safe and produces no external emails or refunds outside the local SQLite database:

```bash
python -m evals.run_evals
python -m evals.report
```

A real LLM demonstration requires `ANTHROPIC_API_KEY` or an OpenAI-compatible provider configured in `.env`; mocked/offline results must be labeled as such in the recording.
