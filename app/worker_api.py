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
from agent.core.verifier import BackendVerifier
from agent.tools.api_client import OpsPilotClient
from agent.tools.api_tools import build_api_tools
from agent.tools.registry import ToolRegistry

router = APIRouter(prefix="/api/worker", tags=["worker"])
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="opspilot")
_lock = threading.Lock()
_runs: dict[str, dict[str, Any]] = {}
_controls: dict[str, dict[str, Any]] = {}


class ApprovalBroker:
    """Block a worker at a risky action until the dashboard decides."""
    def __init__(self):
        self.condition = threading.Condition()
        self.decision: bool | None = None
        self.request: dict[str, Any] | None = None

    def ask(self, tool: Any, arguments: dict, rationale: str) -> bool:
        with self.condition:
            self.decision = None
            self.request = {"name": tool.name, "arguments": arguments, "rationale": rationale}
            self.condition.notify_all()
            while self.decision is None:
                self.condition.wait(timeout=0.5)
            self.request = None
            return self.decision

    def decide(self, approved: bool) -> None:
        with self.condition:
            self.decision = approved
            self.condition.notify_all()

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
        browser_tool = None
        try:
            import os
            if os.getenv("OPSPILOT_BROWSER_ENABLED", "1").lower() not in {"0", "false", "no"}:
                from agent.tools.browser import SyncBrowserTool, build_sync_browser_tools
                browser_tool = SyncBrowserTool(backend_url)
                registry.register_all(build_sync_browser_tools(browser_tool))
        except Exception as exc:
            # A missing browser executable must not hide the reliable API fallback.
            _update(run_id, browser_status=f"unavailable: {exc}")
        cancel_event = threading.Event()
        broker = ApprovalBroker()
        with _lock:
            _controls[run_id] = {"cancel": cancel_event, "approval": broker}
        def prompt_fn(tool, args, rationale):
            _update(run_id, phase="waiting", status="waiting", pending_approval={
                "name": tool.name, "arguments": args, "rationale": rationale}, updated_at=time.time())
            approved = broker.ask(tool, args, rationale)
            _update(run_id, pending_approval=None, updated_at=time.time())
            return approved
        guard = ApprovalPolicy("auto" if request.approve_risky else "ask", prompt_fn=prompt_fn)
        agent = Agent(llm, registry, guard, ask_user=None, max_steps=request.max_steps,
                      on_event=on_event, verifier=BackendVerifier(client), cancel_event=cancel_event)
        result = agent.run(request.task)
        payload = result.to_dict()
        _update(run_id, status=result.status, phase=_phase_for_status(result.status), result=payload,
                current_action=result.summary, finished_at=time.time(), updated_at=time.time())
    except (LLMError, Exception) as exc:
        _update(run_id, status="failed", phase="failed", error=str(exc), current_action=str(exc),
                finished_at=time.time(), updated_at=time.time())
    finally:
        if 'browser_tool' in locals() and browser_tool is not None:
            try:
                browser_tool.close()
            except Exception:
                pass
        with _lock:
            _controls.pop(run_id, None)


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
        "pending_approval": None,
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
            control = _controls.get(run_id)
            if control:
                control["cancel"].set()
                control["approval"].decide(False)
            run.update(status="cancelled", phase="cancelled", current_action="Cancellation requested", updated_at=time.time())
        return _snapshot(run)


class ApprovalRequest(BaseModel):
    approved: bool


@router.post("/runs/{run_id}/approval")
def decide_approval(run_id: str, request: ApprovalRequest):
    with _lock:
        run = _runs.get(run_id)
        control = _controls.get(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if not control or not run.get("pending_approval"):
            raise HTTPException(status_code=409, detail="No approval is pending for this run")
        control["approval"].decide(request.approved)
        run["current_action"] = "Approval received; resuming execution"
        run["updated_at"] = time.time()
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
