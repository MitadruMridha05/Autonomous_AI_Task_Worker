"""Entry point for the Autonomous AI Worker.

Run from the project root (not from inside ``app/``)::

    python -m app.main
    python -m app.main --task "Find the latest invoice from XYZ Ltd and enter it."

Exit status is 0 when the task was completed and verified, 1 when it was not,
and 2 for configuration problems.
"""

import argparse
import logging
import sys

from dotenv import load_dotenv

from app.agent import Approver, AutonomousAgent
from app.config import Settings
from app.exceptions import WorkerError
from app.executor import ToolExecutor
from app.models import AgentResult
from app.planner import LLMPlanner
from app.tools import CompanySystem
from app.verifier import PaymentVerifier

DEFAULT_TASK = """\
Find the latest invoice from ABC Corp,
extract the amount and due date,
enter it into our internal system,
and confirm that it was done.
"""


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx logs one line per API call at INFO, which drowns out the agent trace.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def prompt_for_approval(message: str) -> bool:
    """Ask the person at the terminal; treat a closed stdin as a refusal."""
    print(f"\nHUMAN APPROVAL REQUIRED\n{message}")
    while True:
        try:
            answer = input("Approve? [Y/N]: ").strip().lower()
        except EOFError:
            return False
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False


def build_agent(settings: Settings, approver: Approver | None) -> AutonomousAgent:
    """Wire the components together. This is the only place that knows them all."""
    system = CompanySystem(
        settings.data_dir,
        simulated_payment_failures=settings.simulated_payment_failures,
    )
    verifier = PaymentVerifier(system)
    return AutonomousAgent(
        planner=LLMPlanner(model=settings.openai_model),
        executor=ToolExecutor(system, verifier),
        verifier=verifier,
        max_steps=settings.max_steps,
        approval_threshold=settings.approval_threshold,
        approver=approver,
    )


def print_summary(result: AgentResult) -> None:
    print("\n" + "=" * 60)
    print(f"STATUS  : {result.status.value}")
    print(f"MESSAGE : {result.message}")
    print(f"STEPS   : {result.steps_taken}")
    for item in result.evidence:
        print(f"EVIDENCE: {item.evidence}")
    print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    # Must run before LLMPlanner() so OPENAI_API_KEY from .env is visible.
    load_dotenv()

    parser = argparse.ArgumentParser(description="Autonomous invoice-processing worker.")
    parser.add_argument("--task", default=DEFAULT_TASK, help="Natural-language task.")
    args = parser.parse_args(argv)

    try:
        settings = Settings.from_env()
        configure_logging(settings.log_level)
        agent = build_agent(settings, approver=prompt_for_approval)
    except WorkerError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    result = agent.run(args.task)
    print_summary(result)
    return 0 if result.succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
