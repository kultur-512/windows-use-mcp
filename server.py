"""Windows-Use MCP Server

把 windows-use（基于 Windows UI Automation 的 GUI 自动化 Agent）暴露为 MCP 工具，
作为 ZCode computer-use 的上位替代：通过辅助功能树读取屏幕内容，无需视觉模型即可
操作 Windows 桌面（点击、输入、滚动、快捷键、PowerShell、文件、虚拟桌面等）。

默认是纯工具集模式：所有 wu_* 工具都直接调用 windows-use 底层函数，
**不需要任何模型 API key**。只有开启 Agent 模式才会额外注册 wu_run_task。

运行方式（stdio）:
    python server.py

环境变量（全部可选）:
    WINDOWS_USE_MCP_ENABLE_AGENT  设为 1 时注册 wu_run_task 整包任务工具（需要下面的 LLM 配置）
    WINDOWS_USE_MCP_PROVIDER      anthropic | openai | litellm   (默认 anthropic)
    WINDOWS_USE_MCP_API_KEY       LLM API key
    WINDOWS_USE_MCP_BASE_URL      LLM base url（可用智谱等 Anthropic 兼容接口）
    WINDOWS_USE_MCP_MODEL         模型名 (默认 claude-sonnet-4-5)
    WINDOWS_USE_MCP_MAX_STEPS     wu_run_task 最大步数 (默认 25)
"""

import asyncio
import base64
import logging
import os

from mcp.server.mcpserver import MCPServer
from mcp.types import ImageContent

from windows_use.agent.desktop.service import Desktop
from windows_use.agent.registry.service import Registry
from windows_use.agent.tools import BUILTIN_TOOLS, EXPERIMENTAL_TOOLS

# windows-use 在模块导入时会把 logger 设成 DEBUG 并挂 StreamHandler，
# 这些日志会刷到 stderr（被 ZCode 捕获记录），压到 ERROR 级别并清掉 handler。
for _name in ("windows_use", "windows_use.agent.desktop.service"):
    logging.getLogger(_name).setLevel(logging.ERROR)
    logging.getLogger(_name).handlers = []

server = MCPServer(
    "windows-use",
    title="Windows Use",
    description=(
        "Controls the Windows desktop at the GUI layer via UI Automation: read the "
        "window list and interactive element tree, click, type, scroll, press "
        "shortcuts, run PowerShell, manage files and virtual desktops. "
        "Alternative to computer-use that does not need a vision model."
    ),
)

# 全局单例：Desktop 持有 UIA 连接与 accessibility 树，Registry 持有全部工具函数
desktop = Desktop(use_accessibility=True, use_annotation=True)
registry = Registry(BUILTIN_TOOLS + EXPERIMENTAL_TOOLS)


def _b(v: bool | None) -> str | None:
    """把 MCP 传来的 Python bool 转成 windows-use 要求的 'true'/'false' 字符串。"""
    if v is None:
        return None
    return "true" if v else "false"


async def _run_tool(name: str, params: dict) -> str:
    """调用 windows-use 注册表里的工具，统一异常处理。"""
    try:
        # windows-use 的 SharedBaseModel 要求每个工具调用都带 thought 字段
        params = dict(params)
        params.setdefault("thought", "MCP tool call")
        result = await registry.aexecute(name, params, desktop)
    except Exception as e:  # noqa: BLE001 - 工具错误要回传给 LLM，不能崩掉 server
        return f"Error invoking {name}: {e}"
    if not result.is_success:
        return f"Error: {result.error}"
    return result.content or ""


# ---------------------------------------------------------------------------
# 观察类工具（computer-use 中 getAXState / screenshot 的替代）
# ---------------------------------------------------------------------------


@server.tool()
async def wu_get_state() -> str:
    """获取当前桌面状态：所有打开窗口、活动窗口、虚拟桌面列表。

    在执行任何操作前先调用本工具了解当前环境。返回文本表格。
    """
    state = desktop.get_state()
    parts = ["## Desktops", state.desktops_to_string(), "## Active Window", state.active_window_to_string(), "## Windows", state.windows_to_string()]
    return "\n".join(parts)


@server.tool()
async def wu_get_elements() -> str:
    """获取活动窗口的交互元素树（TOON 格式）。

    返回格式: # id|window|control_type|name|coords|metadata
    id 是元素编号，coords 是元素中心像素坐标。点击/输入/滚动工具使用这些坐标。
    如果返回 "No elements found"，先确认目标窗口在前台（可先调用 wu_app switch）。
    """
    state = desktop.get_state()
    tree = state.tree_state
    if tree is None:
        return "Accessibility tree unavailable."
    return "\n\n".join(
        [
            "## Interactive elements",
            tree.interactive_elements_to_string(),
            "## Scrollable elements",
            tree.scrollable_elements_to_string(),
        ]
    )


@server.tool()
async def wu_screenshot(annotate: bool = False) -> ImageContent:
    """截取当前屏幕，返回 PNG 图片。

    annotate=true 时在截图上的交互元素周围绘制带编号的彩色框（编号与
    wu_get_elements 的元素 id 对应），适合视觉辅助定位。
    """
    state = desktop.get_state()
    nodes = state.tree_state.interactive_nodes if state.tree_state else None
    if annotate and nodes:
        png = desktop.get_annotated_screenshot(nodes=nodes, as_bytes=True)
    else:
        png = desktop.get_screenshot(as_bytes=True)
    return ImageContent(type="image", data=base64.b64encode(png).decode(), mimeType="image/png")


@server.tool()
async def wu_list_apps() -> str:
    """列出开始菜单中可启动的应用程序，供 wu_app(mode='launch') 使用。"""
    apps = desktop.get_apps_from_start_menu()
    if not apps:
        return "No apps found in Start Menu."
    return "\n".join(sorted(apps.keys()))


# ---------------------------------------------------------------------------
# 操作类工具（直接映射 windows-use 的底层工具）
# ---------------------------------------------------------------------------


@server.tool()
async def wu_app(
    mode: str = "launch",
    name: str | None = None,
    loc: list[int] | None = None,
    size: list[int] | None = None,
) -> str:
    """管理应用窗口：launch 从开始菜单启动应用；switch 把已打开的窗口带到前台；
    resize 调整当前活动窗口的位置 (loc=[x,y]) 和尺寸 (size=[w,h])。"""
    return await _run_tool("app_tool", {"mode": mode, "name": name, "loc": loc, "size": size})


@server.tool()
async def wu_click(
    loc: list[int],
    button: str = "left",
    clicks: int = 1,
) -> str:
    """在屏幕坐标 (loc=[x,y]) 处点击。clicks=1 单击、2 双击、0 悬停；
    button 可选 left/right/middle。坐标来自 wu_get_elements。"""
    return await _run_tool("click_tool", {"loc": loc, "button": button, "clicks": clicks})


@server.tool()
async def wu_type(
    loc: list[int],
    text: str,
    clear: bool = False,
    caret_position: str = "idle",
    press_enter: bool = False,
) -> str:
    """点击输入框 (loc=[x,y]) 并输入文字。clear=true 清空原内容；
    caret_position: start/end/idle；press_enter=true 输入后回车提交。
    不要先用 wu_click 点击输入框，本工具会自动聚焦。"""
    return await _run_tool(
        "type_tool",
        {
            "loc": loc,
            "text": text,
            "clear": _b(clear),
            "caret_position": caret_position,
            "press_enter": _b(press_enter),
        },
    )


@server.tool()
async def wu_scroll(
    loc: list[int] | None = None,
    scroll_type: str = "vertical",
    direction: str = "down",
    wheel_times: int = 1,
) -> str:
    """在指定坐标滚动内容；loc 省略则在当前光标位置滚动。
    scroll_type: vertical/horizontal；direction: up/down/left/right；
    每次滚轮约 3-5 行，wheel_times=3-5 中等滚动、10+ 大幅滚动。"""
    return await _run_tool(
        "scroll_tool",
        {"loc": loc, "type": scroll_type, "direction": direction, "wheel_times": wheel_times},
    )


@server.tool()
async def wu_move(loc: list[int], drag: bool = False) -> str:
    """移动鼠标到目标坐标；drag=true 时从当前位置按住左键拖拽到目标（拖放、调整滑块）。"""
    return await _run_tool("move_tool", {"loc": loc, "drag": drag})


@server.tool()
async def wu_shortcut(shortcut: str) -> str:
    """按下键盘快捷键，用 '+' 组合按键，如 'ctrl+c'、'alt+tab'、'win'、'enter'。"""
    return await _run_tool("shortcut_tool", {"shortcut": shortcut})


@server.tool()
async def wu_shell(command: str, timeout: int = 10) -> str:
    """执行 PowerShell 命令并返回输出与退出码。工作目录为用户主目录。
    状态码 0 表示成功。适用于文件操作、系统查询、安装等。"""
    return await _run_tool("shell_tool", {"command": command, "timeout": timeout})


@server.tool()
async def wu_wait(duration: int) -> str:
    """暂停 duration 秒，等待应用启动、页面加载、动画结束。"""
    return await _run_tool("wait_tool", {"duration": duration})


@server.tool()
async def wu_scrape(url: str) -> str:
    """提取浏览器中当前打开网页的可见文本（markdown），基于辅助功能树而非 HTML。"""
    return await _run_tool("scrape_tool", {"url": url})


@server.tool()
async def wu_desktop(
    action: str,
    desktop_name: str | None = None,
    new_name: str | None = None,
) -> str:
    """管理 Windows 虚拟桌面：create 创建（可指定 desktop_name）；
    switch 切换到指定桌面；rename 重命名；remove 删除。"""
    return await _run_tool(
        "desktop_tool", {"action": action, "desktop_name": desktop_name, "new_name": new_name}
    )


@server.tool()
async def wu_file(
    mode: str,
    path: str,
    content: str | None = None,
    destination: str | None = None,
    encoding: str | None = None,
) -> str:
    """文件系统操作：read 读文件、write 写文件、list 列目录、
    delete 删除、move/copy 移动复制、exists 检查存在。
    path 可以是绝对路径或相对用户主目录的相对路径。"""
    return await _run_tool(
        "file_tool",
        {"mode": mode, "path": path, "content": content, "destination": destination, "encoding": encoding},
    )


@server.tool()
async def wu_memory(
    mode: str,
    path: str | None = None,
    content: str | None = None,
    operation: str = "replace",
    old_str: str | None = None,
    new_str: str | None = None,
    line_number: int | None = None,
    read_range: list[int] | None = None,
) -> str:
    """跨步骤持久记忆（保存在 ~/.windows-use/memories/ 的 markdown 文件）。
    mode: view 列出、read 读取、write 写入、update 更新、delete 删除。"""
    return await _run_tool(
        "memory_tool",
        {
            "mode": mode,
            "path": path,
            "content": content,
            "operation": operation,
            "old_str": old_str,
            "new_str": new_str,
            "line_number": line_number,
            "read_range": read_range,
        },
    )


# ---------------------------------------------------------------------------
# 整包任务模式（可选）：WINDOWS_USE_MCP_ENABLE_AGENT=1 时才注册 wu_run_task。
# 未开启时本 server 是纯工具集，不需要任何模型 API。
# ---------------------------------------------------------------------------


def _build_llm():
    """根据环境变量构建 LLM。默认 Anthropic 兼容协议（可用智谱 GLM 的 /api/anthropic）。"""
    provider = os.environ.get("WINDOWS_USE_MCP_PROVIDER", "anthropic")
    api_key = os.environ.get("WINDOWS_USE_MCP_API_KEY")
    base_url = os.environ.get("WINDOWS_USE_MCP_BASE_URL")
    model = os.environ.get("WINDOWS_USE_MCP_MODEL", "claude-sonnet-4-5")
    if provider == "openai":
        from windows_use.providers.openai import ChatOpenAI

        return ChatOpenAI(model=model, api_key=api_key, base_url=base_url)
    if provider == "litellm":
        from windows_use.providers.litellm import ChatLiteLLM

        return ChatLiteLLM(model=model, api_key=api_key, base_url=base_url)
    from windows_use.providers.anthropic import ChatAnthropic

    return ChatAnthropic(model=model, api_key=api_key, base_url=base_url)


if os.environ.get("WINDOWS_USE_MCP_ENABLE_AGENT") == "1":

    @server.tool()
    async def wu_run_task(task: str) -> str:
        """把完整任务交给 windows-use Agent 自动执行（LLM 自主决策，最多 max_steps 步）。

        仅当 server 以 WINDOWS_USE_MCP_ENABLE_AGENT=1 启动时才可用。适合复杂多步任务。
        """
        from windows_use import Agent

        try:
            llm = _build_llm()
        except Exception as e:  # noqa: BLE001
            return f"Error: LLM 配置错误: {e}"
        agent = Agent(
            llm=llm,
            mode="normal",
            max_steps=int(os.environ.get("WINDOWS_USE_MCP_MAX_STEPS", "25")),
            experimental=True,
            log_to_console=False,
        )
        try:
            result = await agent.ainvoke(task=task)
            return result.content
        except Exception as e:  # noqa: BLE001
            return f"Agent error: {e}"


if __name__ == "__main__":
    desktop.warm_up()
    server.run()  # stdio 模式（同步方法，内部自建事件循环）
