"""See the whole Day 1 loop work WITHOUT an API key (real server, real HTTP, real tools, real DB;
only the LLM is a scripted stand-in).

    python -m scripts.smoke_offline

This checks the plumbing. It says nothing about model intelligence: use `python -m agent.cli` with
your real API key for that.
"""
from __future__ import annotations

import gc
import os
import sqlite3
import sys
import tempfile
import time

from agent.cli import print_event
from agent.core.guard import ApprovalPolicy
from agent.core.loop import Agent
from agent.core.scripted import ScriptedLLM
from agent.tools.api_client import OpsPilotClient
from agent.tools.api_tools import build_api_tools
from agent.tools.registry import ToolRegistry
from app.seed import reset_db
from tests.helpers import LiveServer, task1_steps


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "smoke.db")
        os.environ["OPSPILOT_DB"] = db
        reset_db(db)
        
        server = None
        result = None
        try:
            server = LiveServer()
            server.__enter__()
            
            registry = ToolRegistry()
            registry.register_all(build_api_tools(OpsPilotClient(server.url)))
            agent = Agent(ScriptedLLM(task1_steps()), registry, ApprovalPolicy("auto"),
                          runs_dir=None, on_event=print_event)
            result = agent.run("Priya Sharma got a damaged item. Refund her latest order and let her know.")
        finally:
            # Explicitly clean up the server
            if server is not None:
                try:
                    server.__exit__(None, None, None)
                except Exception:
                    pass
            
            # Give threads time to finish
            time.sleep(0.5)
            
            # Force garbage collection to release file handles
            gc.collect()
            time.sleep(0.5)
        
        # Query the database with explicit connection management
        status = None
        mails = None
        try:
            conn = sqlite3.connect(db)
            conn.execute("PRAGMA query_only = ON")
            try:
                status = conn.execute("SELECT status FROM orders WHERE id = 1004").fetchone()[0]
                mails = conn.execute("SELECT COUNT(*) FROM notifications WHERE customer_id = 1").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.OperationalError as e:
            print(f"ERROR: Failed to query database: {e}", file=sys.stderr)
            return 1
    
    print(f"\nAgent status: {result.status} | summary: {result.summary}")
    print(f"Ground truth in DB -> order 1004 status: {status}, emails sent to Priya: {mails}")
    ok = result.ok and status == "refunded" and mails == 1
    print("SMOKE TEST PASSED" if ok else "SMOKE TEST FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
