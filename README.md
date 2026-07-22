# Agentic Infra PoC

A research prototype exploring how far agentic AI can automate software development: give a plain-language spec (e.g. *"build a tic-tac-toe game"*), and a pipeline of AI agents handles requirements, tests, implementation, and verification, with a human checkpoint at each stage.

## What this does

1. You type a spec.
2. **re_engineer** turns it into numbered requirements.
3. **tester** writes real, executable tests (TDD) against those requirements. Here the implementation doesn't exist yet, and the tests are expected to fail until it does.
4. **se_engineer** implements the solution, running the tests itself until they genuinely pass, then verifies the result matches the original spec.
5. You approve or reject each stage's output before the pipeline continues.
6. If the result is a runnable app, it's launched in a persistent container so you can open it.

Every agent runs inside an isolated Docker sandbox with role-restricted tool access (it can only do what its specific job requires) - it never touches your host machine directly.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Build the sandbox image (rebuild this any time mcp_servers/sandbox_server/ changes)
docker build -f sandbox/Dockerfile -t sandbox-server .
```

You'll need a Groq API key (free tier): [console.groq.com/keys](https://console.groq.com/keys)

```bash
export GROQ_API_KEY=your_key_here
```

## Running it

```bash
cd orchestrator
python3 pipeline_runner.py
```

You'll be prompted for a spec, then walked through each stage with a checkpoint menu (approve / reject / view full output) after each one.

### Switching models

```bash
# Default: Groq (llama-3.3-70b-versatile)
python3 pipeline_runner.py

# Local model via llama.cpp
MODEL_PROFILE=llamacpp python3 pipeline_runner.py
# optionally override host/model:
MODEL_PROFILE=llamacpp LLAMACPP_BASE_URL=http://localhost:8080/v1 LLAMACPP_MODEL=your-model python3 pipeline_runner.py
```

### Switching engines (comparison mode)

Instead of the staged MCP pipeline above, hand the whole spec-to-code task to a self-directed coding harness in one shot:

```bash
ENGINE=claude_code python3 pipeline_runner.py   # requires `claude login` already run once on this machine
ENGINE=opencode python3 pipeline_runner.py
```

## Project structure

```
orchestrator/           the control layer - runs everything, holds no LLM logic itself
  pipeline_runner.py      main entry point, stage sequencing, checkpoints, Docker lifecycle
  config.py               pipeline order, docker image name, paths
  state.py                per-run JSON logging to results/run_logs/
  interrupt.py            graceful Ctrl+C handling
  alt_engines.py          Claude Code / opencode integration (comparison arm)

mcp_servers/sandbox_server/   the MCP server - runs INSIDE each Docker container
  server.py                 all tools: file I/O, run_command, git, http_request, background processes
  tools.py                  which role can use which tools
  validation.py             path/command/URL safety checks

llm_client/             talks to whichever LLM is configured
  base.py                 shared provider interface
  agent_provider.py        works with any OpenAI-compatible endpoint (Groq, llama.cpp)
  tool_loop.py             the actual tool-use loop: call model -> execute tool -> feed result back

tui/screens.py          terminal UI (start screen, spec input, checkpoints)

prompts/                one .md file per agent role/a general prompt for claude/opencode.
  re_engineer.md, tester.md, se_engineer.md, full_task.md

sandbox/Dockerfile      the sandbox image definition

demo_projects/          where generated projects actually land
results/run_logs/       JSON log per run: what each stage produced, approved or not
```