import asyncio
import re
import sys
import os
import subprocess
import threading
import time
from pathlib import Path
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp import ClientSession
from textual import work
import config
from state import PipelineState
sys.path.insert(0, str(Path(__file__).parent.parent / "llm_client"))
from agent_provider import OpenAICompatibleProvider
from tool_loop import run_tool_loop
from alt_engines import run_claude_code, run_opencode
from project_layout import verify_via_filesystem


def extract_project_name(text: str) -> str | None:
    # Primary: a PROJECT_NAME/PROJECT-NAME line, any case, optional leading '#'
    match = re.search(r"^#?\s*PROJECT[_-]NAME:?\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    if match:
        return match.group(1).strip().rstrip(":").strip()
    # Fallback: agents sometimes write a bare markdown header instead
    # (e.g. "# quote-finder:") with no PROJECT_NAME phrase at all.
    first_line = next((l for l in text.splitlines() if l.strip()), "")
    header_match = re.match(r"^#\s*([a-zA-Z0-9\-_]+)\s*:?\s*$", first_line.strip())
    return header_match.group(1).strip() if header_match else None


def prepare_project_dir(workspace: Path) -> str | None:
    tests_md = workspace / "tests.md"
    test_file = workspace / "test_solution.py"
    if not tests_md.exists() or not test_file.exists():
        return None

    project_name = extract_project_name(tests_md.read_text())
    if not project_name:
        return None

    project_dir = workspace / project_name
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "test_solution.py").write_text(test_file.read_text())
    return project_name


def load_prompt(role: str) -> str:
    prompt_path = config.PROMPT_DIR / f"{role}.md"
    return prompt_path.read_text() if prompt_path.exists() else ""


def build_docker_params(role: str, workspace: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command="docker",
        args=[
            "run", "-i", "--rm",
            "--user", f"{os.getuid()}:{os.getgid()}",
            "-e", f"AGENT_ROLE={role}",
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

def _prefetch_context(role: str, workspace: Path, project_name: str | None ) -> str:
    if role == "tester":
        paths = ["requirements.md"]
    elif role == "se_engineer":
        paths = ["requirements.md", "tests.md"]
        if project_name:
            paths.append(f"{project_name}/test_solution.py")
    else:
        return ""
    blocks = []
    for rel_path in paths:
        f = workspace / rel_path
        if f.exists():
            blocks.append(f"--- {rel_path} ---\n{f.read_text()}")
    if not blocks:
        return ""
    return (
        "The following files have already been read for you. Their full, current "
        "content is included below. YOU MUST NOT call read_file for these paths; use this "
        "content directly.\n\n" + "\n\n".join(blocks)
    )

def _tool_was_called(tool_calls: list[dict], name: str) -> bool:
    return any(tc["name"] == name for tc in tool_calls)


def _validate_stage(role: str, tool_calls: list[dict], workspace: Path, project_name: str | None = None) -> str | None:
    """Returns None if OK, or a rejection reason string."""
    write_calls = [tc for tc in tool_calls if tc["name"] == "write_file"]
    if role in ("re_engineer", "se_engineer") and not write_calls:
        return "never called write_file"
    if role == "tester":
        paths = {c["arguments"].get("path") for c in write_calls}
        if "tests.md" not in paths:
            return "never wrote tests.md"
        if "test_solution.py" not in paths:
            return "never wrote test_solution.py (TDD requires real test code, not just descriptions)"

        test_content = next(
            (c["arguments"].get("content", "") for c in write_calls
             if c["arguments"].get("path") == "test_solution.py"),
            "",
        )
        try:
            compile(test_content, "test_solution.py", "exec")
        except SyntaxError as e:
            return f"test_solution.py has a syntax error and would never run: {e}"
    if role == "se_engineer":
        passed, verify_output = verify_via_filesystem(workspace, project_name or "project")
        if not passed:
            note = "" if _tool_was_called(tool_calls, "run_command") else " (agent never even attempted to run the tests itself)"
            return f"deterministic verification failed{note} (orchestrator re-ran pytest independently, ignoring the agent's own self-report): {verify_output[:300]}"
    return None


def _find_last_call(tool_calls: list[dict], name: str) -> dict | None:
    matches = [tc for tc in tool_calls if tc["name"] == name]
    return matches[-1] if matches else None


async def run_stage(
    role: str,
    workspace: Path,
    user_input: str,
    state: PipelineState,
    log_path: Path,
    checkpoint_fn,
    log_fn=print,
    project_name: str | None = None,
):
    """Returns (approved: bool, tool_calls: list[dict])."""
    params = build_docker_params(role, workspace)
    provider = build_provider(role)
    prefetched = _prefetch_context(role, workspace, project_name)
    augmented_input = f"{user_input}\n\n{prefetched}" if prefetched else user_input
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            log_fn(f"{role}: Connected, starting...")
            result, tool_calls = await run_tool_loop(
                provider, session, load_prompt(role), augmented_input,
                max_iterations=config.MAX_ITERATIONS_BY_ROLE.get(role, 10),
                log_fn=log_fn,
            )            
            log_fn(f"{role}: Result: {result}")
            rejection_reason = _validate_stage(role, tool_calls, workspace, project_name)
            if rejection_reason:
                log_fn(f"{role}: AUTO-REJECTED - {rejection_reason}. Tool calls: {[c['name'] for c in tool_calls]}")
                state.record(role, result, approved=False)
                state.save(log_path)
                return False, tool_calls

            decision = await checkpoint_fn(role, result, workspace)
            approved = decision == "approve"
            state.record(role, result, approved)
            state.save(log_path)
            return approved, tool_calls


def start_tunnel(port: int, timeout_seconds: int = 20) -> tuple[str | None, subprocess.Popen]:
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    output_buffer: list[str] = []

    def _reader():
        for line in proc.stdout:
            output_buffer.append(line)

    threading.Thread(target=_reader, daemon=True).start()

    url_pattern = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        match = url_pattern.search("".join(output_buffer))
        if match:
            return match.group(0), proc
        time.sleep(0.5)

    proc.terminate()
    return None, proc


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
    print(f"App container '{container_name}' started (docker stop {container_name} to stop it).")
    return f"http://localhost:{config.APP_PORT}"


def run_alt_engine(engine: str, workspace: Path, spec: str) -> tuple[bool, str]:
    prompt = load_prompt("full_task") + "\n\n---\n\nSpec:\n" + spec
    if engine == "claude_code":
        output, returncode = run_claude_code(prompt, workspace)
    elif engine == "opencode":
        output, returncode = run_opencode(prompt, workspace)
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
) -> str | None:

    if engine != "mcp":
        role_fn(engine)
        approved, output = await asyncio.to_thread(run_alt_engine, engine, workspace, spec)
        state.record(engine, output, approved)
        state.save(log_path)
        if not approved:
            log_fn(f"{engine}: AUTO-REJECTED, stopping.")
            return None
        decision = await checkpoint_fn(engine, output, workspace)
        if decision != "approve":
            log_fn(f"{engine}: Not approved, stopping.")
            return None
        log_fn(f"Done. Files in {workspace}")
        return None

    last_tool_calls: list[dict] = []
    project_name = None
    for role in config.PIPELINE_ORDER:
        role_fn(role)
        approved, tool_calls = await run_stage(
            role, workspace, spec, state, log_path,
            log_fn=log_fn, checkpoint_fn=checkpoint_fn, project_name=project_name,
        )
        if role == "se_engineer":
            last_tool_calls = tool_calls
        if not approved:
            log_fn(f"{role}: Not approved, stopping pipeline.")
            return None
        if role == "tester":
            project_name = prepare_project_dir(workspace)
            log_fn(
                f"Project directory '{project_name}' created, test file copied in."
                if project_name else
                "WARNING: could not determine project name / find test files."
            )
    url = launch_persistent_app(last_tool_calls, workspace)
    if not url:
        log_fn("No persistent server was started - files are in the workspace above.")
        return None
    log_fn(f"App running locally: {url}")
    public_url, _tunnel_proc = await asyncio.to_thread(start_tunnel, config.APP_PORT)
    if public_url:
        log_fn(f"App is live on the internet: {public_url}")
    else:
        log_fn("Could not establish a public tunnel - still reachable locally.")
    return public_url