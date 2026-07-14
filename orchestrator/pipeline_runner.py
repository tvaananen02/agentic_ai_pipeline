import asyncio
import sys
import os
from pathlib import Path
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp import ClientSession
from config import DOCKER_IMAGE, PIPELINE_ORDER, DEMO_PROJECT_DIR
from checkpoints import checkpoint
sys.path.insert(0, str(Path(__file__).parent.parent / "llm_client"))
from agent_provider import OpenAICompatibleProvider
from tool_loop import run_tool_loop

PROMPT_DIR = Path(__file__).parent.parent / "prompts"

def load_prompt(role: str) -> str:
    prompt_path = PROMPT_DIR / f"{role}.md"
    return prompt_path.read_text() if prompt_path.exists() else ""
    

def build_docker_params(role: str, workspace: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command="docker",
        args=[
            "run", "-i", "--rm",
            "-e", f"AGENT_ROLE={role}",
            "-v", f"{workspace}:/workspace",
            DOCKER_IMAGE,
        ],
    )

def build_provider(role: str) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        model="llama-3.3-70b-versatile", 
        base_url="https://api.groq.com/openai/v1", 
        api_key=os.environ["GROQ_API_KEY"])

async def run_stage(role: str, workspace: Path, user_input: str):
    params = build_docker_params(role, workspace)
    provider = build_provider(role)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(f"{role}: Connected, starting...")
            result = await run_tool_loop(provider, session, load_prompt(role), user_input)
            print(f"{role}: Result:", result)
            decision = checkpoint(role, result)
            return decision == "approve"

async def main():
    workspace = DEMO_PROJECT_DIR/"test_run"
    os.makedirs(workspace, exist_ok=True)
    spec = "A python program which simulates an atm"
    for role in PIPELINE_ORDER:
        approved = await run_stage(role, workspace, spec)
        if not approved:
            print(f"{role}: Not approved, stopping pipeline.")
            return
    print(f"Pipeline completed successfully. Files in {workspace}")

if __name__ == "__main__":
    asyncio.run(main())