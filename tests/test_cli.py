"""The CLI over *real HTTP* (uvicorn in a thread). Only the LLM is scripted."""
from agent.cli import main
from agent.core.scripted import ScriptedLLM

from .helpers import task1_steps


def test_cli_runs_task1_over_real_http(live_server, query, monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("agent.cli.make_llm", lambda provider, model: ScriptedLLM(task1_steps()))
    code = main(["--url", live_server.url, "--auto-approve", "--runs-dir", str(tmp_path),
                 "Priya Sharma got a damaged item. Refund her latest order and let her know."])
    out = capsys.readouterr().out
    assert code == 0
    assert "Status  : completed" in out and "-> issue_refund(" in out and "approval: APPROVED" in out
    assert query("SELECT status FROM orders WHERE id = 1004")[0]["status"] == "refunded"
    assert len(query("SELECT * FROM notifications WHERE customer_id = 1")) == 1
    assert list(tmp_path.glob("*.json")), "a run trace should have been written"


def test_cli_declines_when_the_human_says_no(live_server, query, monkeypatch, tmp_path):
    from .helpers import call

    steps = task1_steps()[:4] + [call("finish", {"status": "declined", "summary": "Refund declined.", "evidence": []})]
    monkeypatch.setattr("agent.cli.make_llm", lambda provider, model: ScriptedLLM(steps))
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    code = main(["--url", live_server.url, "--runs-dir", str(tmp_path), "Refund Priya's latest order"])
    assert code == 1  # a declined run is not a success
    assert query("SELECT status FROM orders WHERE id = 1004")[0]["status"] == "delivered"


def test_cli_explains_how_to_start_the_app_when_it_is_down(capsys):
    code = main(["--url", "http://127.0.0.1:1", "anything"])
    assert code == 2 and "uvicorn app.main:app" in capsys.readouterr().err
