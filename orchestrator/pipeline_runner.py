import asyncio
import sys
import os
from pathlib import Path
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp import ClientSession
from config import DOCKER_IMAGE, PIPELINE_ORDER, DEMO_PROJECT_DIR
sys.path.insert(0, str(Path(__file__).parent.parent / "llm_client"))
from agent_provider import OpenAICompatibleProvider
from tool_loop import run_tool_loop

TEST_PROMPTS = {
    "re_engineer": "You write requirements. Given a spec, write the requirements to requirements.md, one per line as REQ 1, REQ 2, etc.",
    "tester": "You write tests. Read requirements.md, then write test cases to tests.md as 'TEST 1', 'TEST 2', etc.",
    "se_engineer": "You write code. Read tests.md, then implement the code, and run it to verify it works.",
}

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
    raise ValueError(f"Unknown role: {role}")


async def run_stage(role: str, workspace: Path, user_input: str):
    params = build_docker_params(role, workspace)
    provider = build_provider(role)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print(f"{role}: Connected, starting...")
            result = await run_tool_loop(provider, session, TEST_PROMPTS[role], user_input)
            print(f"{role}: Result:", result)
            return result
            
async def main():
    workspace = DEMO_PROJECT_DIR/"test_run"
    os.makedirs(workspace, exist_ok=True)
    spec = "A python script that checks if a number is even or not"
    for role in PIPELINE_ORDER:
        await run_stage(role, workspace, spec)

if __name__ == "__main__":
    asyncio.run(main())