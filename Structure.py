from pathlib import Path

# Existing project directory
project = Path(".")

# Folders to create inside the existing project
directories = [
    project / "app",
    project / "company_data" / "invoices",
    project / "tests",
]

# Files to create
files = [
    project / "app" / "agent.py",
    project / "app" / "planner.py",
    project / "app" / "executor.py",
    project / "app" / "verifier.py",
    project / "app" / "tools.py",
    project / "app" / "models.py",
    project / "app" / "main.py",

    project / "company_data" / "invoices" / "invoice_abc_001.txt",
    project / "company_data" / "invoices" / "invoice_abc_002.txt",
    project / "company_data" / "invoices" / "invoice_xyz_001.txt",

    project / "company_data" / "payments.json",

    project / "requirements.txt",
    project / "README.md",
    project / ".env",
]

# Create folders
for directory in directories:
    directory.mkdir(parents=True, exist_ok=True)

# Create files
for file in files:
    file.touch(exist_ok=True)

print("✅ Structure created inside:", project.resolve())