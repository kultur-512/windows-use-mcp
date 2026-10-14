"""端到端测试2：操作工具 + 截图 + 应用列表。

用法:
    python test_client2.py [python路径] [server.py路径]
"""
import asyncio
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).resolve().parent
PYTHON = sys.argv[1] if len(sys.argv) > 1 else str(HERE / ".venv" / "Scripts" / "python.exe")
SERVER = sys.argv[2] if len(sys.argv) > 2 else str(HERE / "server.py")


async def main():
    extra_env = {k: v for k, v in os.environ.items() if k.startswith("WINDOWS_USE_MCP")}
    params = StdioServerParameters(command=PYTHON, args=[SERVER], env=extra_env or None)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            for name, args in [
                ("wu_shell", {"command": "echo mcp-test-ok", "timeout": 10}),
                ("wu_list_apps", {}),
                ("wu_wait", {"duration": 1}),
                ("wu_screenshot", {}),
            ]:
                print(f"=== {name} ===")
                res = await session.call_tool(name, args)
                for c in res.content:
                    if getattr(c, "type", None) == "image":
                        print(f"[image] mime_type={c.mime_type} len={len(c.data)} base64")
                    else:
                        print((getattr(c, "text", None) or "")[:500])
                print()


asyncio.run(main())
