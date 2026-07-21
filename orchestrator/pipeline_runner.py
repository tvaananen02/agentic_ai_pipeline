import sys
import os
import re
from pathlib import Path
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp import ClientSession
import config
sys.path.insert(0, str(Path(__file__).parent.parent / "llm_client"))
from agent_provider import OpenAICompatibleProvider
from tool_loop import run_tool_loop
from state import PipelineState
from interrupt import run_with_interrupt
sys.path.insert(0, str(Path(__file__).parent.parent / "tui"))
from screens import start_screen, get_spec, checkpoint_screen, done_screen
import subprocess

def extract_project_name(text: str) -> str | None:
    match = re.search(r"^PROJECT[_-]NAME:\s*(.+)$", text, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else None
 
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
            "-v", f"{workspace}:/workspace",
            "-p", f"{config.APP_PORT}:{config.APP_PORT}",
            config.DOCKER_IMAGE,
        ],
    )

def build_provider(role: str) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        model=config.USED_MODEL, 
        base_url="https://api.groq.com/openai/v1", 
        api_key=os.environ["GROQ_API_KEY"])


def _tool_was_called(tool_calls: list[dict], name: str) -> bool:
    return any(tc["name"] == name for tc in tool_calls)
 
def _validate_stage(role: str, tool_calls: list[dict]) -> str | None:
    write_calls = [tc for tc in tool_calls if tc["name"] == "write_file"]
 
    if role in ("re_engineer", "se_engineer") and not write_calls:
        return "never called write_file"
 
    if role == "tester":
        paths = {c["arguments"].get("path") for c in write_calls}
        if "tests.md" not in paths:
            return "never wrote tests.md"
        if "test_solution.py" not in paths:
            return "never wrote test_solution.py (TDD requires real test code, not just descriptions)"
 
    if role == "se_engineer" and not _tool_was_called(tool_calls, "run_command"):
        return "never called run_command to run the tests"
 
    return None

def _find_last_call(tool_calls: list[dict], name: str) -> dict | None:
    matches = [tc for tc in tool_calls if tc["name"] == name]
    return matches[-1] if matches else None
 
async def run_stage(role: str, workspace: Path, user_input: str, state: PipelineState, log_path: Path):
    """Returns (approved: bool, tool_calls: list[dict])."""
    params = build_docker_params(role, workspace)
    provider = build_provider(role)
 
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(f"{role}: Connected, starting...")
            result, tools_called = await run_tool_loop(provider, session, load_prompt(role), user_input)
            print(f"{role}: Result:", result)
 
            rejection_reason = _validate_stage(role, tools_called)
            if rejection_reason:
                print(f"{role}: AUTO-REJECTED - {rejection_reason}. Tool calls: {[c['name'] for c in tools_called]}")
                state.record(role, result, approved=False)
                state.save(log_path)
                return False, tools_called
 
            decision = checkpoint_screen(role, result)
            approved = decision == "approve"
            state.record(role, result, approved)
            state.save(log_path)
            return approved, tools_called
            
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



async def main():
    if not start_screen():
        return
    spec = get_spec()
    if not spec:
        print("No spec given, exiting.")
        return
    workspace = config.DEMO_PROJECT_DIR / "test_run"
    os.makedirs(workspace, exist_ok=True)
    os.makedirs(config.RUN_LOGS_DIR, exist_ok=True)
 
    log_path = config.RUN_LOGS_DIR / "test_run.json"
    state = PipelineState(spec=spec, project_slug="test_run", workspace=str(workspace))
 
    last_tool_calls: list[dict] = []
    for role in config.PIPELINE_ORDER:
        approved, tool_calls = await run_stage(role, workspace, spec, state, log_path)
        if not approved:
            print(f"{role}: Not approved, stopping pipeline.")
            return
        last_tool_calls = tool_calls if role == "se_engineer" else last_tool_calls
    url = launch_persistent_app(last_tool_calls, workspace)
    done_screen(workspace, log_path)
    if url:
        print(f"App is running: {url}")
    else:
        print("No persistent server was started - files are in the workspace above.")
        
if __name__ == "__main__":
    run_with_interrupt(main())