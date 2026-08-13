# Developer Manual
Practical guide for working on this codebase: what each part does, and how to make common
changes. For deeper review consult the `code_review.md` This document is task-oriented: find the thing you want to do, follow the steps.

## General architecture
A Textual terminal UI (`tui/textual_app.py`) collects a spec, engine, and model from the user,
then calls `run_pipeline()` in `orchestrator/pipeline_runner.py`.  That function starts one
Docker container running an MCP server (`mcp_servers/sandbox_server/server.py`), and walks
through the pipeline order (currently re_engineer -> dev) while switching the containers active role between stages with the `set_role` tool.
Each stage runs `run_tool_loop()`-function, which talks to the configured model via `agent_provider.py` and executes the model's tool calls. After each stage,
`_validate_stage()`checks the result deterministically and if that passes, a human checkpoint is presented in the UI for review, rejection or approval.

```
tui/textual_app.py  →  orchestrator/pipeline_runner.py  →  mcp_servers/sandbox_server/  (in Docker)
                              │                                    ↑
                              └──────────► llm_client/tool_loop.py ┘
                                                  │
                                        prompts/re_engineer.md, dev.md
```
## Where things live
| What | File |
|---|---|
| UI screens, checkpoints | `tui/textual_app.py` |
| Pipeline sequencing, verification | `orchestrator/pipeline_runner.py` |
| All constants (models, paths, budgets) | `orchestrator/config.py` |
| Model/API talk | `llm_client/agent_provider.py` |
| Tool-call loop, retries, auto-test | `llm_client/tool_loop.py` |
| Provider interface (swap models/vendors) | `llm_client/base.py` |
| MCP-tools that exist and their functions | `mcp_servers/sandbox_server/server.py` |
| Role-based tool access control | `mcp_servers/sandbox_server/tools.py` |
| Command/path/URL safety limits | `mcp_servers/sandbox_server/validation.py` |
| Agent instructions | `prompts/re_engineer.md`, `prompts/dev.md` |
| Writes each run's log to `results/run_logs/*.json` | `orchestrator/state.py`, `evaluation/metrics.py` |
| File-location recovery (Claude Code / opencode path) | `orchestrator/project_layout.py` |
|  |  |

---

## How to: change the default model
Edit the value of `USED_MODEL` in `config.py`:
```python
USED_MODEL = os.environ.get("USED_MODEL", "openai/gpt-oss-120b")
```
Or override at runtime without touching code: `USED_MODEL=qwen/qwen3.6-27b python textual_app.py`.

To add a new model as a selectable option in the UI, edit `ModelScreen` in `textual_app.py`:
```python
yield OptionList(
    Option("Groq: qwen/qwen3.6-27b", id="groq:qwen/qwen3.6-27b"),
    Option("Groq: gpt-oss-120b", id="groq:openai/gpt-oss-120b"),
    Option("Groq: your-new-model", id="groq:vendor/your-new-model"),  # add here
)
**Verify the exact model ID with the provider's own docs first**. A wrong or unprefixed ID
produces a 404 at the first call.

---
## How to: add a new tool the agent can call
 
1. Add the function to `mcp_servers/sandbox_server/server.py`, decorated with both `@mcp.tool()`
   and `@require_role`:
```python
   @mcp.tool()
   @require_role
   def your_new_tool(some_arg: str) -> str:
       # do the thing, always return a string
       # on failure, return "ERROR: ..." rather than raising
       return "result text"
```
2. Add its name to whichever role(s) in `TOOL_SETS` (`tools.py`) should be allowed to call it:
```python
   TOOL_SETS = {
       "dev": {..., "your_new_tool"},
   }
```
3. If it runs a shell command, route it through `safe_command` (see `validation.py`) rather than calling `subprocess` directly. This is what enforces the allowlist and forbidden characters.
4. 
4. **Rebuild the Docker image**. The container only sees code baked in at build time:
```bash
   docker build -f sandbox/Dockerfile -t sandbox-server .
```
## How to: add a new pipeline role/stage
 
1. Add the role name to `PIPELINE_ORDER` in `config.py`, in the order it should run:
```python
   PIPELINE_ORDER = ["re_engineer", "your_new_role", "dev"]
```
2. Add its allowed tools to `TOOL_SETS` in `tools.py`.
3. Write `prompts/your_new_role.md` — see `dev.md` for the style.
4. If it needs anything mechanically checked (files written, syntax valid, tests actually
   passed), add a branch to `_validate_stage()` in `pipeline_runner.py`.
5. Rebuild the Docker image (see above) if `tools.py`/`server.py` changed.
---

## How to: adjust how many iterations a role gets
 
Edit `MAX_ITERATIONS_BY_ROLE` in `config.py`:
```python
MAX_ITERATIONS_BY_ROLE = {
    "re_engineer": 8,
    "dev": 30,
}
```

`dev` needs more headroom than `re_engineer` because it reads files, writes tests, writes an
implementation, and iterates on failures. All in one role. If a role you add does less work,
give it a smaller budget; if it needs to iterate a lot, consider giving more iterations to it.

---

## Debugging checklist, in order
 
1. **Did you rebuild the Docker image** after touching `mcp_servers/` or `sandbox/`? This is
   the single most common "my change did nothing" cause.
2. **Read the actual `AUTO-REJECTED` reason in the log**, not just the fact that it was
   rejected. `_validate_stage()` always returns a specific, human-readable reason.
3. **Check `tool_calls` in the saved run log** (`results/run_logs/*.json`). `tool_call_names`
   shows exactly what was called and in what order, which is often more revealing than the
   agent's own final summary text.
4. **If the pipeline crashed outright**, check `results/crash_logs/`. Every unhandled
   exception is caught, logged with a full traceback, and the app exits cleanly instead of
   dying silently.
5. **If something seems to hang**, the `RunningScreen` status line shows exactly what's happening right now. Whether thinking, running a tool, or waiting out
   a rate limit. If that line itself stops updating, that's a real hang; if it's still spinning, it's just slow.
---

## Design principles
- **Never trust the model's own claim of success.** Every meaningful checkpoint re-derives
  the answer from something concrete: real file contents, real captured command output, real
  HTTP responses.
- **Mechanical, repeatable problems belong in code. Model behavior problems belong in prompts**, tightened with concrete examples rather than abstract placeholders. Resist adding a new special-case check for every individual way a model can misbehave about.
- **All verification of generated code happens inside the sandbox container, never on the host.** The host should only ever need Python and Docker, regardless of what any given spec's generated app depends on.
- **Every failure path should end in something legible**. A clear rejection reason, a saved crash log, a cleared workspace. Never a silent hang or an unexplained crash.


