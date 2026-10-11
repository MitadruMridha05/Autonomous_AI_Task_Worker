"""HTTP adapter for the dashboard around the existing OpsPilot agent loop."""
from __future__ import annotations
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import Any
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from agent.config import load_env, opspilot_url
from agent.core.guard import ApprovalPolicy
from agent.core.llm import LLMError, make_llm
from agent.core.loop import Agent
from agent.tools.api_client import OpsPilotClient
from agent.tools.api_tools import build_api_tools
from agent.tools.registry import ToolRegistry

router = APIRouter(prefix="/api/worker", tags=["worker"])
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="opspilot")
_lock = threading.Lock()
_runs: dict[str, dict[str, Any]] = {}

class RunRequest(BaseModel):
    task: str = Field(min_length=3, max_length=4000)
    provider: str | None = None
    model: str | None = None
    max_steps: int = Field(default=20, ge=1, le=50)
    approve_risky: bool = False


def _snapshot(run: dict[str, Any]) -> dict[str, Any]:
    return {**run, "trace": list(run.get("trace", []))}


def _update(run_id: str, **values: Any) -> None:
    with _lock:
        if run_id in _runs:
            _runs[run_id].update(values)


def _execute(run_id: str, request: RunRequest, backend_url: str) -> None:
    def on_event(event: dict[str, Any]) -> None:
        phase = {
            "start": "planning", "llm": "planning", "tool_call": "running",
            "tool_result": "running", "approval": "waiting", "ask_user": "waiting",
            "error": "failed", "finish": "completed",
        }.get(event.get("kind"), "running")
        with _lock:
            current = _runs.get(run_id)
            if current is not None:
                current["trace"].append(event)
                current["phase"] = phase
                current["current_action"] = _friendly_event(event)
                current["updated_at"] = time.time()

    try:
        load_env()
        client = OpsPilotClient(backend_url)
        client.health()
        llm = make_llm(request.provider, request.model)
        registry = ToolRegistry()
        registry.register_all(build_api_tools(client))
        guard = ApprovalPolicy("auto" if request.approve_risky else "deny")
        agent = Agent(llm, registry, guard, ask_user=None, max_steps=request.max_steps, on_event=on_event)
        result = agent.run(request.task)
        payload = result.to_dict()
        _update(run_id, status=result.status, phase=_phase_for_status(result.status), result=payload,
                current_action=result.summary, finished_at=time.time(), updated_at=time.time())
    except (LLMError, Exception) as exc:
        _update(run_id, status="failed", phase="failed", error=str(exc), current_action=str(exc),
                finished_at=time.time(), updated_at=time.time())


def _phase_for_status(status: str) -> str:
    if status in {"completed", "no_action_needed"}:
        return "completed"
    if status in {"needs_clarification", "declined"}:
        return "waiting"
    return "failed"


def _friendly_event(event: dict[str, Any]) -> str:
    kind = event.get("kind")
    if kind == "start": return "Task accepted; preparing an execution plan"
    if kind == "llm": return "Reasoning about the next safe action"
    if kind == "tool_call": return f"Calling {event.get('name', 'worker tool')}"
    if kind == "tool_result": return f"Received {'verified result' if event.get('ok') else 'an error'} from {event.get('name', 'tool')}"
    if kind == "approval": return "Risky action approval was handled by the selected policy"
    if kind == "error": return event.get("message", "Worker error")
    if kind == "finish": return event.get("summary", "Execution finished")
    return "Worker is active"

@router.post("/run", status_code=202)
def start_run(request: RunRequest, http_request: Request):
    run_id = __import__("uuid").uuid4().hex[:8]
    now = time.time()
    run = {
        "run_id": run_id, "task": request.task, "status": "queued", "phase": "queued",
        "trace": [], "current_action": "Queued for the next available worker slot",
        "created_at": now, "updated_at": now, "result": None, "error": None,
        "settings": request.model_dump(exclude={"task"}),
    }
    with _lock:
        _runs[run_id] = run
    backend_url = str(http_request.base_url).rstrip("/")
    _executor.submit(_execute, run_id, request, backend_url)
    return _snapshot(run)

@router.get("/runs")
def list_runs():
    with _lock:
        return [_snapshot(r) for r in sorted(_runs.values(), key=lambda item: item["created_at"], reverse=True)]

@router.get("/runs/{run_id}")
def get_run(run_id: str):
    with _lock:
        run = _runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _snapshot(run)

@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    with _lock:
        run = _runs.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run["status"] in {"queued", "running", "planning", "waiting"}:
            run.update(status="cancelled", phase="cancelled", current_action="Cancellation requested", updated_at=time.time())
        return _snapshot(run)

@router.get("/settings")
def worker_settings():
    import os
    return {
        "provider": os.getenv("LLM_PROVIDER", "anthropic"),
        "model": os.getenv("LLM_MODEL", "provider default"),
        "max_steps": 20,
        "approval_mode": "manual confirmation required unless enabled per run",
        "api_base": opspilot_url(),
    }
