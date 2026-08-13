import asyncio
import re
import sys
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp import ClientSession
import config
from state import PipelineState
sys.path.insert(0, str(Path(__file__).parent.parent / "llm_client"))
from agent_provider import OpenAICompatibleProvider
from tool_loop import run_tool_loop
from alt_engines import run_claude_code, run_opencode
from project_layout import verify_via_filesystem

def extract_project_name(text: str) -> str | None:
    match = re.search(r"^#?\s*PROJECT[_-]NAME:?\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if match:
        return match.group(1).strip().rstrip(":").strip()
    first_line = next((l for l in text.splitlines() if l.strip()), "")
    header_match = re.match(r"^#\s*([a-zA-Z0-9\-_]+)\s*:?\s*$", first_line.strip())
    return header_match.group(1).strip() if header_match else None

def determine_project_name(workspace: Path) -> str | None:
    req = workspace / "requirements.md"
    if not req.exists():
        return None
    return extract_project_name(req.read_text())

def load_prompt(role: str) -> str:
    prompt_path = config.PROMPT_DIR / f"{role}.md"
    return prompt_path.read_text() if prompt_path.exists() else ""

def _prefetch_context(role: str, workspace: Path, project_name: str | None) -> str:
    if role != "dev":
        return ""
    paths = ["requirements.md"]
    blocks = []
    for rel_path in paths:
        f = workspace / rel_path
        if f.exists():
            blocks.append(f"--- {rel_path} ---\n{f.read_text()}")
    if not blocks:
        return ""
    return (
        "The following files have already been read for you - their full, current "
        "content is included below. Do not call read_file for these paths; use this "
        "content directly.\n\n" + "\n\n".join(blocks)
    )

def build_docker_params(workspace: Path, initial_role: str) -> StdioServerParameters:
    return StdioServerParameters(
        command="docker",
        args=[
            "run", "-i", "--rm",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "-e", f"AGENT_ROLE={initial_role}",
            "-e", "HOME=/tmp",
            "-p", f"{config.APP_PORT}:{config.APP_PORT}",
            "-v", f"{workspace}:/workspace",
            config.DOCKER_IMAGE,
        ],
    )

def build_provider(role: str) -> OpenAICompatibleProvider:
    if config.MODEL_PROFILE == "llamacpp":
        return OpenAICompatibleProvider(
            model=config.LLAMACPP_MODEL,
            base_url=config.LLAMACPP_BASE_URL,
            api_key="not-needed",
        )
    return OpenAICompatibleProvider(
        model=config.USED_MODEL,
        base_url="https://api.groq.com/openai/v1",
        api_key=os.environ["GROQ_API_KEY"],
    )

def _last_test_result(tool_calls: list[dict]) -> tuple[bool, str] | None:
    for tc in reversed(tool_calls):
        command = tc.get("arguments", {}).get("command", "")
        if tc["name"] == "run_command" and "pytest" in command:
            output = tc.get("result", "")
            passed = (
                "exit code: 0" in output
                and "passed" in output.lower()
                and "failed" not in output.lower()
                and "error" not in output.lower()
            )
            return passed, output
    return None

def _validate_stage(role: str, tool_calls: list[dict], workspace: Path, project_name: str | None = None) -> str | None:
    """Returns None if OK, or a rejection reason string."""
    write_calls = [tc for tc in tool_calls if tc["name"] == "write_file"]
    if role == "re_engineer" and not write_calls:
        return "never called write_file"

    if role == "dev":
        paths = {c["arguments"].get("path", "") for c in write_calls}
        if not any(p.endswith("test_solution.py") for p in paths):
            return "never wrote test_solution.py (TDD requires real test code, not just descriptions)"
        if not any(p.endswith("solution.py") for p in paths):
            return "never wrote solution.py"

        test_content = next(
            (c["arguments"].get("content", "") for c in write_calls
             if c["arguments"].get("path", "").endswith("test_solution.py")),
            "",
        )
        try:
            compile(test_content, "test_solution.py", "exec")
        except SyntaxError as e:
            return f"test_solution.py has a syntax error and would never run: {e}"

        test_result = _last_test_result(tool_calls)
        if test_result is None:
            return "no pytest run was ever recorded - solution.py was written but never verified to actually pass"
        passed, output = test_result
        if not passed:
            tail = output[-600:] if len(output) > 600 else output
            return f"the real pytest run inside the sandbox did not pass: ...{tail}"
    return None

def _find_last_call(tool_calls: list[dict], name: str) -> dict | None:
    matches = [tc for tc in tool_calls if tc["name"] == name]
    return matches[-1] if matches else None

def _clear_workspace(workspace: Path) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

def _finish_failed_pipeline(state: PipelineState, log_path: Path, workspace: Path) -> None:
    state.finish()
    state.save(log_path)
    _clear_workspace(workspace)

async def run_stage_in_session(
    session: ClientSession,
    role: str,
    workspace: Path,
    user_input: str,
    state: PipelineState,
    log_path: Path,
    checkpoint_fn,
    log_fn=print,
    status_fn=None,
    project_name: str | None = None,
):
    """Returns (approved: bool, tool_calls: list[dict]). Reuses an
    already-open session/container - switches role instead of restarting
    Docker per stage."""
    result = await session.call_tool("set_role", {"role": role})
    result_text = "".join(block.text for block in result.content if hasattr(block, "text"))
    if result_text.startswith("ERROR"):
        raise RuntimeError(f"Failed to switch role to '{role}': {result_text}")
    log_fn(f"  {result_text}")

    provider = build_provider(role)

    prefetched = _prefetch_context(role, workspace, project_name)
    augmented_input = f"{user_input}\n\n{prefetched}" if prefetched else user_input

    log_fn(f"{role}: starting...")
    result_text2, tool_calls = await run_tool_loop(
        provider, session, load_prompt(role), augmented_input,
        max_iterations=config.MAX_ITERATIONS_BY_ROLE.get(role, 10),
        log_fn=log_fn,
        status_fn=status_fn,
    )
    log_fn(f"{role}: Result: {result_text2}")
    rejection_reason = _validate_stage(role, tool_calls, workspace, project_name)
    if rejection_reason:
        log_fn(f"{role}: AUTO-REJECTED - {rejection_reason}. Tool calls: {[c['name'] for c in tool_calls]}")
        state.record(role, result_text2, approved=False, rejection_reason=rejection_reason, tool_calls=tool_calls)
        state.save(log_path)
        return False, tool_calls

    decision = await checkpoint_fn(role, result_text2, workspace)
    approved = decision == "approve"
    state.record(
        role, result_text2, approved,
        rejection_reason=None if approved else f"rejected by checkpoint: {decision}",
        tool_calls=tool_calls,
    )
    state.save(log_path)
    return approved, tool_calls

def _wait_for_local_app(port: int, timeout_seconds: int = 15) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://localhost:{port}", timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False

def launch_persistent_app(tool_calls: list[dict], workspace: Path) -> str | None:
    bg_call = _find_last_call(tool_calls, "start_background")
    if not bg_call:
        return None
    command = bg_call["arguments"].get("command")
    if not command:
        return None
    container_name = f"agentic-app-{os.getpid()}"
    subprocess.run(
        [
            "docker", "run", "-d",
            "--name", container_name,
            "--user", f"{os.getuid()}:{os.getgid()}",
            "-e", "HOME=/tmp",
            "-p", f"{config.APP_PORT}:{config.APP_PORT}",
            "-v", f"{workspace}:/workspace",
            "--entrypoint", "",
            config.DOCKER_IMAGE,
            "sh", "-c", f"cd /workspace && {command}",
        ],
        check=False,
    )
    if not _wait_for_local_app(config.APP_PORT):
        print(f"App container '{container_name}' started but never responded on port {config.APP_PORT} - check `docker logs {container_name}`.")
        return None
    print(f"App container '{container_name}' started and responding (docker stop {container_name} to stop it).")
    return f"http://localhost:{config.APP_PORT}"

def run_alt_engine(engine: str, workspace: Path, spec: str) -> tuple[bool, str]:
    prompt = load_prompt("full_task") + "\n\n---\n\nSpec:\n" + spec
    if engine == "claude_code":
        output, returncode = run_claude_code(prompt, workspace)
    elif engine == "opencode":
        output, returncode = run_opencode(prompt, workspace, model="opencode/big-pickle")
    else:
        raise ValueError(f"Unknown config.ENGINE: {engine}")
    print(f"[{engine}] finished, returncode={returncode}")
    print(f"[{engine}] output: {output[:500]}")
    passed, verify_output = verify_via_filesystem(workspace, "project")
    if not passed:
        print(f"[{engine}] AUTO-REJECTED - tests did not actually pass:\n{verify_output[:500]}")
        return False, output
    return True, output

async def run_pipeline(
    engine: str,
    spec: str,
    workspace: Path,
    log_path: Path,
    state: PipelineState,
    checkpoint_fn,
    log_fn=print,
    role_fn=lambda role: None,
    status_fn=None,
) -> str | None:

    if engine != "mcp":
        role_fn(engine)
        approved, output = await asyncio.to_thread(run_alt_engine, engine, workspace, spec)
        state.record(engine, output, approved)
        state.save(log_path)
        if not approved:
            log_fn(f"{engine}: AUTO-REJECTED, stopping.")
            _finish_failed_pipeline(state, log_path, workspace)
            return None
        decision = await checkpoint_fn(engine, output, workspace)
        if decision != "approve":
            log_fn(f"{engine}: Not approved, stopping.")
            _finish_failed_pipeline(state, log_path, workspace)
            return None
        state.finish()
        state.save(log_path)
        log_fn(f"Done. Files in {workspace}")
        return None

    last_tool_calls: list[dict] = []
    project_name = None
    params = build_docker_params(workspace, config.PIPELINE_ORDER[0])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        for role in config.PIPELINE_ORDER:
            role_fn(role)
            approved, tool_calls = await run_stage_in_session(
                session, role, workspace, spec, state, log_path,
                log_fn=log_fn, checkpoint_fn=checkpoint_fn,
                status_fn=status_fn, project_name=project_name,
            )
            if role == "dev":
                last_tool_calls = tool_calls
            if not approved:
                log_fn(f"{role}: Not approved, stopping pipeline.")
                _finish_failed_pipeline(state, log_path, workspace)
                return None
            if role == "re_engineer":
                project_name = determine_project_name(workspace)
                log_fn(
                    f"Project name determined: '{project_name}'"
                    if project_name else
                    "WARNING: could not determine project name from requirements.md."
                )

    url = launch_persistent_app(last_tool_calls, workspace)
    state.record_deploy(url)
    state.finish()
    state.save(log_path)
    if not url:
        log_fn("No persistent server was started - files are in the workspace above.")
        return None
    log_fn(f"App running locally: {url}")
    return url