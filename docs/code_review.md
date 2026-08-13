# Code review
Summary of a full codebase walkthrough.


## Part 1: Codebase walkthrough
 
### 1. `tui/textual_app.py` - the user's perspective
 
This is the application's **only real entry point**. Everything else is a library this file
calls into.
 
#### Screen flow
 
```
StartScreen → SpecScreen → EngineScreen → (ModelScreen, if mcp) → RunningScreen
                                                                        ↓
                                                                  CheckpointScreen (per stage)
```
 
- **`StartScreen`**: Welcome screen, two options: start or quit.
- **`SpecScreen`**: Text field where the user types the spec. Stored on `self.app.spec`,
  then moves on.
- **`EngineScreen`**: Choose the execution mode, either the MCP pipeline, or a pre-built
  agent tool (Claude Code / opencode). Sets `config.ENGINE` directly at module level. This
  works because `config` is a plain Python module, and module attributes are effectively
  global for the whole process.
- **`ModelScreen`**: Only shown if the custom pipeline was chosen. Picks the model
  (`qwen/qwen3.6-27b` or `openai/gpt-oss-120b` at the moment), sets `config.MODEL_PROFILE` and
  `config.USED_MODEL`.
- **`RunningScreen`**: A live log view (`RichLog` widget) where every tool call and its
  result print as they happen, plus a continuously updating status line.
- **`CheckpointScreen`**: Pauses execution after every stage. Three options: Approve,
  Reject, or View any file written so far. This reads the file **straight off disk** so the user always sees the real content.

#### How this connects to the orchestrator
 
```python
async def checkpoint_fn(role: str, artifact: str, ws: Path) -> str:
    return await self.push_screen_wait(CheckpointScreen(role, artifact, ws))
 
await run_pipeline(
    config.ENGINE, self.spec, workspace, log_path, state,
    checkpoint_fn=checkpoint_fn, log_fn=running.log_line,
    role_fn=running.set_role, status_fn=running.set_status,
)
```
 
`checkpoint_fn` is a closure passed into `run_pipeline` as a parameter. The orchestrator
doesn't know or care that this is a Textual screen. It just calls a function that returns
`"approve"` or something else, and waits for the answer. UI and orchestration logic are
completely decoupled, connected only through function parameters.
 
The entire `_run_pipeline` method is wrapped in a `try/except` block that logs any unhandled
exception to `results/crash_logs/` and exits the app cleanly.

### 2. `orchestrator/config.py` — all constants in one place
 
```python
PIPELINE_ORDER = ["re_engineer", "dev"]
DOCKER_IMAGE = "sandbox-server"
USED_MODEL = os.environ.get("USED_MODEL", "openai/gpt-oss-120b")
MODEL_PROFILE = os.environ.get("MODEL_PROFILE", "groq")
MAX_ITERATIONS_BY_ROLE = {"re_engineer": 8, "dev": 30}
KNOWN_ARTIFACT_DIRS = {".pytest_cache", "__pycache__", ".git"}
REQUIRED_PROJECT_FILES = ["solution.py", "test_solution.py"]
```

- **`PIPELINE_ORDER`** is a list, not a fixed pair. The `for role in config.PIPELINE_ORDER:`
  loop works-as-is regardless of the number of roles in `PIPELINE_ORDER`.
- **`MAX_ITERATIONS_BY_ROLE`** is per-role because `dev` does more work (reads, writes, tests,
  iterates) than `re_engineer`.
- **`os.environ.get(..., default)`** everywhere allows overriding via environment variable
  without touching code.
`config` contains no logic, only values. Every other file imports it.

---

### 3. `orchestrator/pipeline_runner.py`: The orchestration core
#### `run_pipeline`: where everything starts
 
```python
params = build_docker_params(workspace, config.PIPELINE_ORDER[0])
async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
    await session.initialize()
    for role in config.PIPELINE_ORDER:
        ...
```
One Docker container starts and **stays open for the entire `for` loop**.

#### `run_stage_in_session`: one stage's lifecycle
1. Switch role (`set_role`), check the return value doesn't start with `"ERROR"`. If it
   does, the function raises `RuntimeError`, since running the rest of the pipeline under the
   wrong role would be worse than a visible crash.
2. Preload known context (`_prefetch_context`) e.g. `requirements.md`'s content is attached
   directly to `dev`'s first message.
3. Run `run_tool_loop` (see section 5).
4. Check the result with `_validate_stage`.
5. If the mechanical check passes, call `checkpoint_fn`.



#### `_validate_stage`: what's actually checked
 
```python
test_result = _last_test_result(tool_calls)
```
 
This is the core of the whole system's reliability. `_last_test_result` scans `tool_calls`
**backwards** for the most recent real `run_command` call that ran `pytest`. It reads the real output that was captured inside the container.

#### Deployment: two separate containers
 
```python
def launch_persistent_app(tool_calls, workspace):
    bg_call = _find_last_call(tool_calls, "start_background")
    ...
    subprocess.run(["docker", "run", "-d", ...])
    if not _wait_for_local_app(config.APP_PORT):
        return None
    return f"http://localhost:{config.APP_PORT}"
```
 
Starts a **new, persistent container** running the same command the `dev` agent used to test
the server during development, but yet a different container from the development one, which is
already closed by this point. `_wait_for_local_app` polls the port for up to 15 seconds
before giving up.

### 4. `mcp_servers/sandbox_server/` — what happens inside the container
 
#### `tools.py`: who's allowed to do what
 
```python
TOOL_SETS = {
    "re_engineer": {"read_file", "write_file", "list_dir"},
    "dev": {"read_file", "write_file", "list_dir", "run_command",
            "git_commit", "git_push", "http_request",
            "start_background", "get_background_output", "stop_background"},
}
```
 
A dict, role name as key, allowed tool names as the value. `re_engineer` can't run commands
or start servers.
 
#### `server.py`: the actual tools
 
- **`AGENT_ROLE`** is a global variable, re-read on every tool call (inside the
  `require_role` decorator).
- **`set_role`** is the only tool without `@require_role`, since its entire purpose is to
  switch roles. This is never shown to the agent, only the orchestrator
  calls it directly.
- **`write_file`** auto-corrects the possible case where the model writes a literal `\n` (backslash +
  n) instead of a real newline.
- **`run_command`** vs. **`start_background`**: the former waits for the command to finish
  (fits tests), the latter doesn't (fits servers, which never exit on their own).
- **`git_commit`/`git_push`** exist but are untested

#### `validation.py`: what's allowed
 
```python
ALLOWED_COMMANDS: set[str] = {
    "python",
    "python3",
    "pytest",
}

WHITELISTED_DOMAINS: set[str] = {
    "localhost",
    "onrender.com"
}

``` 
`safe_command` rejects any command whose executable isn't in this set, and also forbids
certain chaining characters. `safe_url` allows only `localhost` and `onrender.com` addresses. `Render.com` is considered a valid future development point for public deployment of the apps built with this pipeline. Not currently supported.

### 5. `llm_client/tool_loop.py` — the model/tool conversation loop
The basic loop: ask the model what it wants to do, execute it, tell the model the result, ask
again, until the model stops requesting tools or iterations run out.

 **`_extract_pseudo_tool_calls`**: Recognizes after the fact when the model writes a tool
  call as text (`<function(name)(...)>`) instead of using the real protocol, and executes it
  anyway.
- **`_CACHEABLE_TOOLS = {"write_file"}`**: Only file writes can be safely cached. Nothing
  else is ever cached, because a case was observed where a stale, cached test result misled
  the agent about its own progress.
- **`_truncate_for_history(..., keep_end=...)`**: `run_command` results are truncated from
  the **front**, not the end, since pytest's actual pass/fail verdict is always at the end of
  the message.
- **`_maybe_auto_test`**: The instant `solution.py` is written, `pytest` runs automatically,
  deterministically, regardless of whether the agent asked for it. Removes the dependency on
  the agent's own memory ("did it remember to run the tests").
- **`_call_with_retry`**: Groq TPM rate-limit errors are detected and recovered from
  automatically, using the wait time suggested in the error message itself.
  - **`status_fn`**: A continuously updating status message (`"[3/30] Thinking..."`,
    `"Running write_file..."`, `"Rate limited - waiting 7s..."`) for the UI, so slowness doesn't
    look like a hang.

### 6. `orchestrator/project_layout.py` — file reconciliation
 
A standalone piece whose job is making sure `solution.py` and `test_solution.py` end up in
the same, correct directory.
 
```python
def reconcile_project_layout(workspace, project_name):
    candidate_dirs = [...]
    # one candidate → use it
    # no candidate → create one, named after project_name
    # multiple candidates → match by name, or fall back to most recently modified
    for filename in REQUIRED_PROJECT_FILES:
        # find the file at the workspace root or in any subdirectory,
        # move it into place if it isn't already there
```
 
Principle: instead of **assuming** the correct directory name up front, the function
**discovers** the directory that actually got created afterward and corrects any mismatch.
 
Currently used via `verify_via_filesystem`, which in turn is used by the `run_alt_engine`
path (Claude Code / opencode) — the custom pipeline's own verification now comes straight
from `tool_calls` history (`_last_test_result`).

### 7. `prompts/re_engineer.md` and `prompts/dev.md` — what the agent is actually told
 
#### `re_engineer.md`
 
A narrow, tightly scoped task: turn the spec into a numbered requirements list, write it to
`requirements.md` in an exact format. Includes a concrete example of the correct format,
because it was repeatedly observed that the model confused the literal `PROJECT_NAME:` label
with the actual project name when given only an abstract placeholder.
 
#### `dev.md`
 
A longer, multi-stage role that combines testing and implementation. Two sections are
especially strict, directly in response to repeatedly observed failures:
 
- **"Web Application Detection"** requires, unconditionally, that if the spec implies a
  browser-facing application, the tests must exercise a real Flask test client, and the
  implementation must genuinely run as a server and respond.
- **"Persistent servers"** spells out exactly how to start a server, and stresses that the
  `process_id` returned by `start_background` must be used verbatim in subsequent calls.
---

## Summary: how the pieces connect
 
```
textual_app.py (user)
      │  spec, engine, model
      ▼
pipeline_runner.py (orchestrator, on the host)
      │  starts one container, switches role inside it
      ▼
server.py + tools.py (MCP server, inside the container)
      │  exposes a role-restricted tool set
      ▼
tool_loop.py (model/tool loop)
      │  talks to the language model, executes tool calls
      ▼
prompts/*.md (instructions telling the model what to do)
```
