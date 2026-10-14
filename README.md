# Windows-Use MCP Server

把 [windows-use](https://github.com/Jeomon/Windows-Use)（基于 **Windows UI Automation** 的桌面 GUI 自动化库）封装为 **MCP server**，作为 computer-use / 桌面自动化类工具的上位替代：

- 通过辅助功能树（UIA）读取屏幕内容，**不需要视觉模型**，比截图识别更快更准
- 可以操作**后台窗口**（不抢焦点）
- 纯工具集模式**不需要任何模型 API key** —— ZCode / Claude / Cursor 等客户端的模型直接驱动这些工具

> ⚠️ **安全警告**：本服务能操控整个桌面、运行 PowerShell、读写文件，可造成不可逆更改。
> 建议在虚拟机 / Windows Sandbox 中部署，或仅在你信任的任务中使用。

---

## 特性

- **纯工具集模式（默认）**：16 个工具直接调用 windows-use 底层函数，零模型依赖
- **Agent 模式（可选）**：设置 `WINDOWS_USE_MCP_ENABLE_AGENT=1` 后额外注册 `wu_run_task`，
  把自然语言任务交给 windows-use 内置 Agent 完整执行（此时才需要 LLM API key）
- 支持虚拟桌面、持久记忆、网页抓取、文件操作

## 工具清单

在 MCP 客户端里工具名形如 `mcp__windows-use__wu_xxx`。

### 观察类（先调用这些了解环境）

| 工具 | 作用 |
|---|---|
| `wu_get_state` | 所有打开窗口、活动窗口、虚拟桌面列表（表格） |
| `wu_get_elements` | 活动窗口的**交互元素树**（TOON 格式：`# id\|window\|control_type\|name\|coords\|metadata`），点击/输入的坐标来源 |
| `wu_screenshot` | 返回 PNG 截图；`annotate=true` 时在元素周围画带编号彩色框 |
| `wu_list_apps` | 开始菜单可启动的应用列表 |

### 操作类

| 工具 | 作用 |
|---|---|
| `wu_app` | `launch` 启动应用 / `switch` 切换窗口 / `resize` 调整活动窗口 |
| `wu_click` | 坐标点击：`clicks=1/2/0`（单击/双击/悬停）、`button=left/right/middle` |
| `wu_type` | 点击输入框并输入；`clear=true` 清空、`press_enter=true` 提交 |
| `wu_scroll` | 滚动（方向、次数） |
| `wu_move` | 移动鼠标 / `drag=true` 拖拽 |
| `wu_shortcut` | 快捷键，如 `ctrl+c`、`alt+tab` |
| `wu_shell` | 执行 PowerShell 命令，返回输出和退出码 |
| `wu_wait` | 暂停 N 秒等待界面变化 |
| `wu_scrape` | 抓取浏览器当前页面的可见文本（markdown） |
| `wu_desktop` | 虚拟桌面：`create/switch/rename/remove` |
| `wu_file` | 文件操作：`read/write/list/delete/move/copy/exists` |
| `wu_memory` | 跨步骤记忆（存 `~/.windows-use/memories/`） |

### Agent 模式（可选）

| 工具 | 作用 |
|---|---|
| `wu_run_task` | 完整自然语言任务交给 windows-use Agent 自主执行（需 `WINDOWS_USE_MCP_ENABLE_AGENT=1` + LLM 配置） |

## 安装

要求：Windows 10/11，Python 3.10+

```bash
git clone https://github.com/kultur-512/windows-use-mcp.git windows-use-mcp
cd windows-use-mcp
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

> 注：`requirements.txt` 把 `mistralai` 固定到 `<2`，因为 windows-use 0.8.1 与 mistralai 3.x 不兼容
> （`cannot import name 'Mistral'`）。

## 配置到 MCP 客户端

### ZCode（`~/.zcode/cli/config.json`）

```json
{
  "mcp": {
    "servers": {
      "windows-use": {
        "type": "stdio",
        "command": "C:\\path\\to\\windows-use-mcp\\.venv\\Scripts\\python.exe",
        "args": ["C:\\path\\to\\windows-use-mcp\\server.py"],
        "timeoutMs": 60000
      }
    }
  }
}
```

### Claude Desktop / 其他客户端（`.mcp.json` 或 `claude_desktop_config.json`）

```json
{
  "mcpServers": {
    "windows-use": {
      "command": "C:\\path\\to\\windows-use-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\windows-use-mcp\\server.py"]
    }
  }
}
```

启动较慢（首次要生成 comtypes 类型库，1-2 秒），建议把超时调大到 60s。

### 开启 Agent 模式（可选）

```json
"env": {
  "WINDOWS_USE_MCP_ENABLE_AGENT": "1",
  "WINDOWS_USE_MCP_PROVIDER": "anthropic",
  "WINDOWS_USE_MCP_API_KEY": "sk-...",
  "WINDOWS_USE_MCP_BASE_URL": "https://open.bigmodel.cn/api/anthropic",
  "WINDOWS_USE_MCP_MODEL": "glm-5.3"
}
```

`provider` 支持 `anthropic`（含兼容接口）/ `openai` / `litellm`。

## 典型使用流程

让客户端模型这样工作：

1. `wu_get_state` —— 看当前有哪些窗口
2. `wu_app` switch 到目标窗口（或 launch 启动应用）
3. `wu_get_elements` —— 拿目标元素坐标
4. `wu_click` / `wu_type` 操作
5. 需要视觉确认时 `wu_screenshot annotate=true`

示例任务："打开记事本写一首关于 Windows 的诗并保存"：

```
1. wu_app(mode="launch", name="Notepad")
2. wu_wait(duration=2)
3. wu_get_elements()            # 找到编辑器区域坐标
4. wu_type(loc=[...], text="Windows 的诗……")
5. wu_shortcut(shortcut="ctrl+s")
6. wu_get_elements()            # 找到保存对话框
7. wu_type(loc=[...], text="poem.txt", press_enter=true)
```

Agent 模式可以一步到位：`wu_run_task(task="打开记事本写一首关于 Windows 的诗并保存到 poem.txt")`

## 自测

```bash
# 端到端测试 1：列出工具 + 调用观察工具
python test_client.py

# 端到端测试 2：操作工具（PowerShell/截图/应用列表）
python test_client2.py
```

## 排障

- **工具返回 `thought:Field required`** —— 旧版 windows-use 要求每个工具调用带 `thought` 字段，
  server 已自动注入，升级到最新代码即可。
- **MCP 显示 failed / 超时** —— 首次启动需生成 comtypes 类型库，把 `timeoutMs` 调到 60000；
  仍失败则用配置里的 command + args 手动在终端跑一遍看报错。
- **`cannot import name 'Mistral' from 'mistralai'`** —— 执行
  `pip install "mistralai>=1.9.11,<2"`。
- **元素树为空 / 窗口找不到** —— 先用 `wu_app` switch 把目标窗口带到前台，再 `wu_get_elements`。

## License

MIT（本项目的 LICENSE 与上游 windows-use 同为 MIT，使用/分发时请保留上游版权声明）。
