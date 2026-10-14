"""端到端测试：以 MCP stdio 客户端连接 server，列出工具并调用几个观察工具。

用法:
    python test_client.py [python路径] [server.py路径]
默认使用同目录 .venv 下的 python 和 server.py。
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
    # mcp 客户端不继承全部环境变量，显式透传 WINDOWS_USE_MCP_*（如 ENABLE_AGENT）
    extra_env = {k: v for k, v in os.environ.items() if k.startswith("WINDOWS_USE_MCP")}
    params = StdioServerParameters(command=PYTHON, args=[SERVER], env=extra_env or None)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"TOOLS ({len(tools.tools)}):")
            for t in tools.tools:
                print(f"  - {t.name}: {t.description.splitlines()[0] if t.description else ''}")

            for name, args in [
                ("wu_get_state", {}),
                ("wu_get_elements", {}),
            ]:
                print(f"\n=== call {name} ===")
                try:
                    res = await session.call_tool(name, args)
                    for c in res.content:
                        txt = getattr(c, "text", None)
                        if txt:
                            print(txt[:800])
                        else:
                            print(f"[{c.type} content]")
                except Exception as e:
                    print(f"CALL FAILED: {e}")


asyncio.run(main())
