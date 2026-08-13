# What this is?

A prototype exploring how far agentic AI can automate software development: give a
plain-language spec (e.g. *"build a web app with a counter"*), and a pipeline of AI agents
handles requirements, tests, implementation, and verification, with a human checkpoint at each
stage. The final result launched is a app, running on `localhost`.

## What the prototype does?

1. You type a spec into the terminal UI.
2. A requirements engineer agent turns it into numbered requirements.
3. A dev agent writes, executable tests against those requirements, then implements the
   solution, running the tests itself inside the sandbox until they pass. If the spec
   describes a web application, it also starts it as a real server and confirms it responds
   before finishing.
4. The orchestrator(plain python code and logic) independently re-checks the real test output captured from inside the
   sandbox before ever showing anything to you.
5. You approve, reject, or inspect any file's real contents at each checkpoint before the
   pipeline continues.
6. If the result is a runnable app, it's launched in a persistent container so you can open it
   at `http://localhost:8000`.

Both agent roles share a single Docker sandbox for the whole run, with role-restricted tool
access. Each role can only do what its specific job requires. Nothing runs on your host
machine except the orchestrator itself; the host never needs any of the generated project's own
dependencies (e.g. Flask) installed.

## Setup
In the project root directory, run:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Build the sandbox image (rebuild this any time mcp_servers/sandbox_server/ or sandbox/ changes)
docker build -f sandbox/Dockerfile -t sandbox-server .
```

You'll need a Groq API key (free tier): [console.groq.com/keys](https://console.groq.com/keys)

```bash
export GROQ_API_KEY=your_key_here
```

## Running it

```bash
cd tui
python3 textual_app.py
```

This opens the terminal UI. You'll be asked for a spec, then an engine and model, and walked
through each stage with a checkpoint (approve / reject / view any file's real content) after it.

### Switching models

Model and engine selection happens interactively in the UI, but both can also be set via
environment variables before launch:

```bash
# Default: Groq (openai/gpt-oss-120b)
python3 textual_app.py

# A different Groq model
USED_MODEL=llama-3.3-70b-versatile python3 textual_app.py

# Local model via llama.cpp
MODEL_PROFILE=llamacpp python3 textual_app.py
# optionally override host/model:
MODEL_PROFILE=llamacpp LLAMACPP_BASE_URL=http://localhost:8080/v1 LLAMACPP_MODEL=your-model python3 textual_app.py
```

### Switching engines (comparison mode)

Instead of the staged MCP pipeline above, hand the whole spec-to-code task to a self-directed
coding harness in one shot, connected through the same sandbox:

```bash
ENGINE=claude_code python3 textual_app.py   # Requires that `claude login` was already run once on this machine
ENGINE=opencode python3 textual_app.py
```

### Fast iteration without the UI

For debugging or running the same spec repeatedly to check success rate, use the headless
script instead - no manual clicking, auto-approves every checkpoint:

```bash
cd orchestrator
python3 headless_run_script.py "a web app with a counter" --model openai/gpt-oss-120b --runs 3
```

## Project structure

```
orchestrator/              the control layer, runs everything, holds no LLM logic itself
  pipeline_runner.py         stage sequencing, checkpoints, single shared Docker session,
                              deterministic verification against real in-sandbox test output
  config.py                  pipeline order, paths, per-role iteration
                              budgets, model defaults
  state.py                   per-run JSON logging to results/run_logs/
  project_layout.py          deterministic project-directory reconciliation (used by the
                              Claude Code / opencode comparison arm)
  alt_engines.py              Claude Code / opencode integration (comparison arm)
  headless_run_script.py      CLI runner for fast, unattended repeat testing

mcp_servers/sandbox_server/   the MCP server, runs inside the shared Docker container
  server.py                    all tools: file I/O, run_command, git, http_request, background
                                processes, plus set_role (orchestrator-only, switches which
                                role's tool set is active without restarting the container)
  tools.py                     which role (re_engineer / dev) can use which tools
  validation.py                 path/command/URL safety checks

llm_client/                 talks to whichever LLM is configured
  base.py                     shared provider interface
  agent_provider.py            works with any OpenAI-compatible endpoint (Groq, llama.cpp)
  tool_loop.py                 the tool-use loop: call model -> execute tool -> feed result
                                back, with recovery for malformed tool calls and safe history
                                truncation

tui/textual_app.py          terminal UI, the actual entry point (engine/model selection,
                             live tool-call stream, checkpoints with real file previews)

prompts/                    one .md file per agent role
  re_engineer.md, dev.md      currently used by the pipeline
  tester.md, se_engineer.md    kept from an earlier three-stage design, not currently used
  full_task.md                 combined prompt for Claude Code / opencode

sandbox/Dockerfile          the sandbox image definition
demo_projects/               where a run's generated project lands
results/run_logs/            JSON log per run: what each stage produced, approved or not
results/crash_logs/          full stack trace if the pipeline crashes unexpectedly
evaluation/                  metrics.py, smoke_test.py, benchmarking, in progress
```

## Notes

- The pipeline currently deploys to `localhost` only.
- All verification happens from real output captured inside the sandbox container, never by re-running anything on the host. The host only ever
  needs Python and Docker, regardless of what a given spec's generated app depends on.
- `tester.md` / `se_engineer.md` reflect an earlier three-stage pipeline
  (`re_engineer -> tester -> se_engineer`, one container per stage) that was simplified into
  the current two-stage, single-container design. The files are kept in case that split is
  useful again later, but nothing currently loads them.
