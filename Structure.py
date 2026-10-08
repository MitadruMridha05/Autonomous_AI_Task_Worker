import os

# Root project directory
PROJECT_NAME = "."

# Directories to create
directories = [
    # Mock company app
    "app/templates",

    # Agent
    "agent/core",
    "agent/tools",
    "agent/prompts",

    # Interface
    "interface",

    # Evaluation
    "evals/tasks",

    # Tests
    "tests",

    # Docker
    "docker",

    # GitHub Actions
    ".github/workflows",

    # Monitoring
    "monitoring",
]

# Files to create
files = [
    # -------------------------
    # APP
    # -------------------------
    "app/main.py",
    "app/db.py",
    "app/seed.py",
    "app/chaos.py",

    "app/templates/login.html",
    "app/templates/customers.html",
    "app/templates/orders.html",
    "app/templates/refund.html",

    # -------------------------
    # AGENT CORE
    # -------------------------
    "agent/core/loop.py",
    "agent/core/planner.py",
    "agent/core/verifier.py",
    "agent/core/memory.py",
    "agent/core/guard.py",
    "agent/core/failures.py",
    "agent/core/llm.py",

    # -------------------------
    # AGENT TOOLS
    # -------------------------
    "agent/tools/base.py",
    "agent/tools/registry.py",
    "agent/tools/browser.py",
    "agent/tools/api.py",
    "agent/tools/files.py",

    # -------------------------
    # AGENT SCHEMAS
    # -------------------------
    "agent/schemas.py",

    # -------------------------
    # PROMPTS
    # -------------------------
    "agent/prompts/system_v1.txt",
    "agent/prompts/planner_v1.txt",
    "agent/prompts/verifier_v1.txt",

    # -------------------------
    # INTERFACE
    # -------------------------
    "interface/cli.py",
    "interface/streamlit_app.py",

    # -------------------------
    # EVALUATION
    # -------------------------
    "evals/run_evals.py",
    "evals/report.py",

    # Example evaluation task
    "evals/tasks/invoice_task.yaml",

    # -------------------------
    # TESTS
    # -------------------------
    "tests/test_planner.py",
    "tests/test_tools.py",
    "tests/test_verifier.py",

    # -------------------------
    # DVC / CONFIG
    # -------------------------
    "dvc.yaml",
    "params.yaml",

    # -------------------------
    # DOCKER
    # -------------------------
    "docker/Dockerfile",
    "docker/docker-compose.yml",

    # -------------------------
    # CI/CD
    # -------------------------
    ".github/workflows/ci.yml",

    # -------------------------
    # MONITORING
    # -------------------------
    "monitoring/README.md",

    # -------------------------
    # PROJECT DOCS
    # -------------------------
    "README.md",
    ".gitignore",
    "requirements.txt",
]


def create_project_structure():
    # Create root directory
    os.makedirs(PROJECT_NAME, exist_ok=True)

    # Create directories
    for directory in directories:
        path = os.path.join(PROJECT_NAME, directory)
        os.makedirs(path, exist_ok=True)

    # Create files
    for file in files:
        path = os.path.join(PROJECT_NAME, file)

        # Make sure parent directory exists
        parent_directory = os.path.dirname(path)

        if parent_directory:
            os.makedirs(parent_directory, exist_ok=True)

        # Create empty file
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                f.write("")

    print("=" * 50)
    print("Project structure created successfully!")
    print("=" * 50)
    print(f"Location: {os.path.abspath(PROJECT_NAME)}")


if __name__ == "__main__":
    create_project_structure()