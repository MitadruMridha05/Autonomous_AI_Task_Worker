# Dashboard outcomes

- Add a polished responsive dashboard at `/worker` with product name, natural-language task composer, example task chips, validation, run/cancel controls, and settings.
- Integrate the dashboard with the existing FastAPI health, audit, customer/order data, and a worker execution adapter that reuses the existing `Agent` loop and API tools.
- Show live run status, elapsed time, current step, progress, readable status messages, and a chronological activity timeline sourced from the agent trace.
- Show completed, failed, cancelled, and needs-clarification result states with evidence, metrics, copy, retry, edit-and-retry, and feedback controls.
- Add searchable/filterable task history with status, duration, steps, open, re-run, and delete affordances where supported by the local in-process history.
- Add backend/system status, model/provider status, settings for supported worker configuration, responsive styling, accessible labels/focus states, loading/error/empty/offline states, and toast feedback.
- Document frontend setup, `VITE_API_BASE_URL`, worker endpoint behavior, and local run commands in README.
- Add frontend build/typecheck validation and preserve existing Python tests.
