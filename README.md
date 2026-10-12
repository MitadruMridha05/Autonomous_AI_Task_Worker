# Autonomous AI Task Worker --- Demo & Recording Guide

**Repository:**
[MitadruMridha05/Autonomous_AI_Task_Worker](https://github.com/MitadruMridha05/Autonomous_AI_Task_Worker)\
**Goal:** Record a concise, recruiter-focused demo showing the worker
planning, using tools, recovering from a failure, applying safety
controls, and verifying the actual application state.

> **Important:** Only show features and results that you have run
> successfully on your machine. The repository's offline evaluation uses
> scripted model turns; distinguish it from a live LLM run. Never show
> API keys, `.env` values, tokens, or private customer data.

------------------------------------------------------------------------

## Table of contents

-   [Demo story](#demo-story)
-   [Recommended 4-minute video](#recommended-4-minute-video)
-   [Setup on Windows PowerShell](#setup-on-windows-powershell)
-   [Run the dashboard](#run-the-dashboard)
-   [Run the evaluation and tests](#run-the-evaluation-and-tests)
-   [Demo scenario prompts](#demo-scenario-prompts)
-   [Narration script](#narration-script)
-   [Recording checklist](#recording-checklist)
-   [Troubleshooting](#troubleshooting)
-   [Publish the demo](#publish-the-demo)

## Demo story

**Title:** *Give the AI a Task. Watch It Work.*

Present the project as an agentic workflow, not just a chatbot. The
worker receives a natural-language objective, plans actions, calls
tools, observes outcomes, decides what to do next, and verifies the
result against application/backend state.

Use a realistic task from the repository's mock business environment.
The current repo documentation describes customer/order/refund workflows
and invoice CSV export, so prefer these supported examples over an
invoice-payment scenario unless that payment workflow exists in the
current code.

## Recommended 4-minute video

  -----------------------------------------------------------------------
  Time                    Show                    What the recruiter
                                                  should learn
  ----------------------- ----------------------- -----------------------
  0:00--0:20              Project title and task  The worker accepts a
                          input in `/worker`      natural-language
                                                  objective

  0:20--1:15              Live execution trace    Plan, tool calls,
                                                  observations, and
                                                  decisions

  1:15--2:00              One-time browser/UI     The agent can respond
                          failure and API         to a real failure
                          fallback                

  2:00--2:35              Ambiguous identity or   It asks for
                          risky action            clarification or
                                                  applies an approval
                                                  gate

  2:35--3:20              Final status and        Success is checked
                          backend verification    independently of the
                                                  model's claim

  3:20--4:00              Evaluation report,      Reliability and
                          tests, architecture     engineering quality are
                                                  measurable
  -----------------------------------------------------------------------

If one scene is not working reliably, do not fake it. Replace it with a
scenario that runs successfully and explain any limitation honestly.

------------------------------------------------------------------------

## Setup on Windows PowerShell

Run these commands from the repository root.

``` powershell
git clone https://github.com/MitadruMridha05/Autonomous_AI_Task_Worker.git
cd Autonomous_AI_Task_Worker

py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, use this for the current terminal
session only:

``` powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

Create a local environment file if you need to configure a live model
provider:

``` powershell
Copy-Item .env.example .env
notepad .env
```

Fill in only the variables documented in `.env.example`. Keep the file
private and out of Git. **Never paste its contents into the video or
commit it.** Offline deterministic evaluations can be run without a live
provider key.

Install the browser used by the recovery test:

``` powershell
python -m playwright install chromium
```

## Run the dashboard

Build the frontend once (Node.js/npm must be installed):

``` powershell
npm --prefix frontend install
npm --prefix frontend run build
```

Start the backend from the repository root:

``` powershell
uvicorn app.main:app --reload --port 8000
```

Open the dashboard in your browser:

``` text
http://localhost:8000/worker
```

Keep the server terminal open while using the dashboard. If the UI is
blank or outdated after a frontend change, rebuild the frontend and
refresh the page.

### Optional: run a live CLI task

Use only against the local seeded/mock application. This example can
perform a refund and customer notification, so understand the approval
behavior before running it:

``` powershell
python -m agent.cli --auto-approve "Priya Sharma got a damaged item. Refund her latest order and let her know."
```

`--auto-approve` bypasses the normal human approval pause for the run.
Use it only in the local demo environment and only when you intend to
approve the risky action.

------------------------------------------------------------------------

## Run the evaluation and tests

These commands provide reproducible evidence. Run them before recording,
then show the actual output.

### 1. Test suite

``` powershell
pytest -q
```

### 2. Deterministic evaluation suite

``` powershell
python -m evals.run_evals
```

The repository documentation describes nine deterministic scenarios. The
offline suite uses scripted model turns and local application data; it
is useful for regression testing but should not be presented as proof of
live model reasoning.

### 3. Generate the report

``` powershell
python -m evals.report
```

Expected report artifacts documented by the repository:

``` text
runs/report/report.md
runs/report/task_results.png
```

Open these files only if they were generated successfully in your
current run.

### 4. Browser-to-API recovery test

``` powershell
python -m playwright install chromium
pytest -q tests/test_browser_api_recovery.py
```

When this test passes, it is evidence that the test injected a one-time
browser/UI failure, the API fallback completed the operation, and
backend verification checked the resulting state. Show the real test
output and explain that this is a test scenario if you are not
demonstrating it live in the dashboard.

### 5. Optional live-provider evaluation

This requires a configured OpenAI-compatible provider and a valid
credential. It may incur API charges.

``` powershell
python -m evals.run_live_evals --model gpt-5-mini
```

The repo documents results at:

``` text
runs/live_eval_results.json
runs/live/
```

Do not run this if your provider is not configured or you do not want to
incur API costs. Do not claim the live evaluation passed unless your own
run confirms it.

### 6. Optional Docker run

Make sure Docker Desktop is running first. From the repository root:

``` powershell
Set-Location docker
docker compose up --build app
```

When finished, stop the containers with `Ctrl+C`, then:

``` powershell
docker compose down
```

The repo documentation notes that the Docker configuration was
written/validated, but an image build had not been run in the documented
environment. Verify the build on your own machine before claiming Docker
execution works.

### 7. Optional DVC pipeline

From the repository root, if DVC is installed:

``` powershell
dvc repro
```

------------------------------------------------------------------------

## Demo scenario prompts

Paste prompts into the `/worker` task field one at a time. The exact
seeded names, IDs, and available actions may vary; use the data actually
present in your local app.

### Scenario A --- Normal task (primary scene)

``` text
Priya Sharma got a damaged item. Find her latest order, check its current status and refund eligibility, refund it if eligible, notify the customer, and verify the final order and refund state. If any required detail is ambiguous or the action needs approval, stop and ask rather than guessing.
```

**Show:** task submission, plan, tool calls, observations, any approval
prompt, final status, and verification evidence.

### Scenario B --- Browser failure and API recovery

``` text
Find the eligible order for Priya Sharma and process the refund. If the browser action fails, inspect the error, decide whether a safe fallback is available, use the supported API fallback if appropriate, and verify that exactly one refund record exists. Do not repeat a refund blindly.
```

**How to demonstrate it:** use the repository's documented
failure-injection test or UI controls if available. Do not claim a
failure was injected unless you actually triggered it. If the dashboard
has no user-facing injection control, show the dedicated test
command/output instead of improvising hidden steps.

### Scenario C --- Ambiguous identity / clarification

``` text
Find the customer named John and refund his order. If more than one customer matches, do not choose one. Ask me which customer or order I mean, and make no changes until the ambiguity is resolved.
```

**Show:** the ambiguity, the clarification request, and that no risky
change was made before clarification.

### Scenario D --- Risky action / approval

``` text
Inspect Priya Sharma's latest order and determine whether it qualifies for a refund. Before issuing a refund or sending an outbound customer message, pause for explicit human approval. If approval is not granted, make no risky change and report what remains undone.
```

**Show:** the approval gate and the resulting behavior. If the dashboard
has an "Approve risky actions" option, leave it disabled first to
demonstrate the default safe behavior.

### Scenario E --- Invoice CSV export

``` text
Find all invoices that are more than 30 days overdue, export the matching records to a CSV file, and report the output path and number of records. Verify that the file exists and that the exported rows match the filtered records.
```

Use this only if invoice records and CSV export are implemented and
working in the checked-out version.

### Scenario F --- Already completed / no-op

``` text
Inspect the requested order and its current refund state before taking action. If it has already been refunded, do not issue another refund. Verify the existing state and report that no additional action was needed.
```

**Show:** safe no-op behavior and protection against duplicate actions,
if supported by the current implementation.

------------------------------------------------------------------------

## Narration script

Use this as a guide rather than reading every word. Speak naturally and
keep the execution visible.

### Opening --- 0:00--0:20

> "This is my Autonomous AI Task Worker. Instead of asking an AI only
> for an answer, I give it a business objective. The worker plans the
> steps, uses available tools, observes the results, and checks whether
> the requested outcome actually happened."

### During execution --- 0:20--1:15

> "Here I'm submitting a task in natural language. The trace lets us
> inspect the worker's actions: what it planned, which tool it called,
> what came back, and how it decided what to do next. The goal is to
> make the execution inspectable rather than hiding it behind a final
> response."

### Failure recovery --- 1:15--2:00

> "Now I'm demonstrating the recovery path. The first UI operation
> fails. The worker needs to observe that failure and choose a supported
> alternative, rather than blindly repeating a potentially risky action.
> I'll show the actual fallback and the verification result."

### Safety --- 2:00--2:35

> "The worker also needs to know when not to act. If the customer
> identity is ambiguous, it should ask for clarification. For risky
> actions such as refunds or outbound messages, the approval gate keeps
> a human in control."

### Verification --- 2:35--3:20

> "A model saying 'done' is not enough. The application state is checked
> independently, so the result can be compared with the intended
> outcome. I'll show the status and evidence produced by this run."

### Closing --- 3:20--4:00

> "This project combines agent orchestration, tool integration, failure
> handling, safety controls, and evaluation. The test suite and
> evaluation report help measure behavior across multiple scenarios. The
> next step is to keep improving reliability and expand the supported
> workflows."

Edit the narration to match what actually appears on screen. Remove any
sentence that claims a feature or result you did not demonstrate.

------------------------------------------------------------------------

## Recording checklist

### Before recording

-   [ ] Start from a clean terminal and confirm the repository root.
-   [ ] Run the test suite and evaluation commands; save the genuine
    output.
-   [ ] Confirm the dashboard opens at `http://localhost:8000/worker`.
-   [ ] Test the primary task, recovery, clarification, approval, and
    verification scenes.
-   [ ] Increase terminal font size and close unrelated windows/tabs.
-   [ ] Disable desktop notifications.
-   [ ] Hide API keys, `.env`, account details, and personal data.
-   [ ] Prepare a backup plan: show the actual recovery test output if
    live injection is unavailable.

### Recording settings and editing

-   Use OBS Studio or another screen recorder.
-   Record at 1080p if your laptop can handle it; keep browser and
    terminal text readable.
-   Record microphone narration in a quiet room.
-   Capture the browser dashboard and terminal output; switch between
    them deliberately.
-   Cut dead time and setup mistakes, but retain the real task execution
    and evidence.
-   Add short captions such as **Plan**, **Tool call**, **Failure
    observed**, **Fallback**, **Approval**, and **Backend verified**.
-   Keep the final video around 3--4 minutes. Do not fabricate logs or
    edit a failed result to look successful.

### Suggested file name

``` text
autonomous-ai-task-worker-demo.mp4
```

------------------------------------------------------------------------

## Troubleshooting

### Dashboard does not load

1.  Confirm the virtual environment is active.
2.  Confirm frontend dependencies are installed and the build succeeded.
3.  Start the backend from the repository root.
4.  Check the terminal for import errors or a port conflict.
5.  Open `http://localhost:8000/worker` again.

### Provider or API error

-   Check the variable names and provider setup documented in
    `.env.example`.
-   Confirm the model name is supported by the configured provider.
-   Never share your secret key while troubleshooting.
-   If the provider is unavailable, use the offline deterministic
    evaluation for regression evidence and clearly label it as
    offline/scripted.

### Docker API / engine error

-   Start Docker Desktop and wait until its engine is ready.
-   Run `docker version` to confirm the CLI can connect to the engine.
-   Then retry the Docker Compose command from the `docker` directory.

### Recovery scene is not reproducible

-   Run `pytest -q tests/test_browser_api_recovery.py`.
-   Use the test output as evidence of the automated failure-recovery
    scenario.
-   Do not claim the dashboard itself has a manual failure-injection
    button unless you have verified that control exists.

### Report files are missing

Run these commands in order:

``` powershell
python -m evals.run_evals
python -m evals.report
```

Then check `runs/report/` for the generated report and chart.

------------------------------------------------------------------------

## Publish the demo

1.  Upload the finished video to an accessible location such as YouTube
    (Unlisted is suitable for sharing with recruiters) or attach it to a
    GitHub release.
2.  Copy the actual video URL.
3.  Add it near the top of the repository's main `README.md`, for
    example:

``` markdown
## Project Demo

[Watch the 3–4 minute demo](PASTE_YOUR_REAL_VIDEO_URL_HERE)

The demo shows a natural-language task, agent execution trace, failure recovery,
safety/approval behavior, and backend verification.
```

4.  Replace the placeholder with the real URL; do not leave a fake link
    in the repository.
5.  Commit and push the README update:

``` powershell
git status
git add README.md
git commit -m "docs: add autonomous worker demo video"
git push origin main
```

If you saved this guide as a separate file such as
`docs/demo-recording-guide.md`, adjust the `git add` path accordingly.

------------------------------------------------------------------------

## Final principle

**Show evidence, not promises.** A strong demo proves one complete task,
one genuine recovery path, a safety decision, and an independently
checked result. The video should make it easy for a recruiter to
understand both what the worker does and how you know it worked.
