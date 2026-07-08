import asyncio
import os
from pathlib import Path
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp import ClientSession

async def main():
    workspace = str(Path(__file__).parent.parent / "demo_projects" / "test_run")
    os.makedirs(workspace, exist_ok=True)

    params = StdioServerParameters(
        command="docker",
        args=[
            "run", "-i", "--rm",
            "-e", "AGENT_ROLE=se_engineer",
            "-v", f"{workspace}:/workspace",
            "sandbox-server",
        ],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Connected. Tools:", [t.name for t in tools.tools])

asyncio.run(main())