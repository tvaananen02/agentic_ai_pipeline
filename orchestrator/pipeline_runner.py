import asyncio
import os
from pathlib import Path
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp import ClientSession
from config import DOCKER_IMAGE, PIPELINE_ORDER, DEMO_PROJECT_DIR

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

async def run_stage(role: str, workspace: Path):
    params = build_docker_params(role, workspace)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"{role}: Connected. Tools:", [t.name for t in tools.tools])
            return tools

async def main():
    workspace = DEMO_PROJECT_DIR/"test_run"
    os.makedirs(workspace, exist_ok=True)
    for role in PIPELINE_ORDER:
        await run_stage(role, workspace)

if __name__ == "__main__":
    asyncio.run(main())