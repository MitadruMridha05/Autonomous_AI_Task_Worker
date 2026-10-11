# OpsPilot dashboard plan

## Implementation
- Preserve the existing FastAPI mock company APIs and HTML routes.
- Add a worker adapter under `app/worker_api.py` that reuses `agent.core.loop.Agent`, `make_llm`, `OpsPilotClient`, and `build_api_tools` rather than duplicating agent behavior.
- Expose `/api/worker/run`, `/api/worker/runs`, `/api/worker/runs/{run_id}`, and `/api/worker/runs/{run_id}/cancel` for dashboard execution and run history. Run state is kept in-process for the local prototype; completed traces reuse the agent's existing persisted JSON trace.
- Add a React + TypeScript + Vite frontend under `frontend/`, built into `app/static/worker-ui` and served by FastAPI at `/worker`.
- Use `VITE_API_BASE_URL` for deployments where the frontend is served separately; same-origin is the default.
- Add a route manifest at `frontend/public/manus-routes.json` and update README setup instructions.

## Design
- **Design movement:** editorial dark observability console — calm, dense enough for operators, but with a warm paper-like content surface for results.
- **Core principles:** one obvious next action; evidence over decoration; operational clarity; progressive disclosure for technical details.
- **Color philosophy:** deep ink/navy surfaces create focus, electric blue marks live execution, mint confirms verified outcomes, amber signals approval/waiting, and coral is reserved for failure.
- **Layout paradigm:** persistent slim rail + asymmetric two-column command center; the task composer spans the workbench while execution and context sit beside it.
- **Signature elements:** blue orbital mark, hairline grid texture, and status pills with compact monospace metadata.
- **Interaction philosophy:** fast, reversible, keyboard-friendly. Example tasks seed the composer; destructive work makes approval explicit; technical event payloads stay collapsed.
- **Animation:** subtle shimmer only for live state, 160ms panel transitions, no looping neon effects.
- **Typography:** Inter for UI hierarchy, IBM Plex Mono for IDs, timestamps, and telemetry.
- **Brand essence:** a trustworthy cockpit for autonomous operations; precise, calm, transparent.
- **Brand voice:** direct and reassuring. “Give the worker a clear outcome.” “Every action is traceable.”
- **Wordmark/logo:** compact orbital node mark beside the OpsPilot wordmark.
- **Signature brand color:** electric blue `#5b8cff`.

## Main components
`AppShell`, `Sidebar`, `TopBar`, `TaskComposer`, `ExecutionCard`, `ActivityTimeline`, `ResultPanel`, `HistoryPanel`, `SystemStatus`, `SettingsDrawer`, and reusable status/telemetry primitives.
