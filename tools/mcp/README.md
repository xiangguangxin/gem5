# gem5 MCP + Tools

让 agent（Claude Code）通过 MCP 工具**接入 GitHub**、**编译 gem5**、**跑 SE 仿真**。

挂载两个 MCP server：

| server | 作用 | 来源 |
|---|---|---|
| `github` | PR / Issue / Repo / Actions 等 GitHub 操作 | 官方 `github/github-mcp-server`（远程 HTTP 模式） |
| `gem5` | `gem5_build` / `gem5_simulate` / `gem5_status` | 本仓库自建（`tools/mcp/gem5_mcp/server.py`） |

## 目录结构

```
tools/mcp/
├── README.md              # 本文件
├── requirements.txt       # mcp>=1.2,<2.0
├── gem5_mcp/
│   ├── __init__.py
│   └── server.py          # FastMCP server，3 个工具
└── configs/
    └── x86-hello.py       # 默认 SE 仿真脚本（X86DemoBoard + x86-hello64-static）
```

## 前置条件

1. **Python 3.10+**（已用 3.13 验证）。
2. **安装依赖**：
   ```bash
   pip3 install -r tools/mcp/requirements.txt
   ```
   注意：锁定 `mcp<2.0`，因为 `mcp` 2.0 是重写后的新 API（`MCPServer`），
   与社区通行的 `FastMCP`（1.x）不兼容。
3. **GitHub PAT**（仅 `github` server 需要）：到 GitHub
   `Settings → Developer settings → Personal access tokens` 创建一个 token，
   勾选 `repo`（或 fine-grained：读仓库内容 + PR/Issue 读写）权限，然后：
   ```bash
   export GITHUB_PERSONAL_ACCESS_TOKEN=ghp_xxx
   ```
   `.mcp.json` 通过 `${GITHUB_PERSONAL_ACCESS_TOKEN}` 展开，**仓库不提交真实 token**。

## 挂载方式

### 方式一：项目级 `.mcp.json`（随仓库管理，推荐）

仓库根已提供 `.mcp.json`。首次在 Claude Code 打开本项目时，会提示你批准这两个
project-scoped server（或 `/mcp` 里手动启用）。用 `claude mcp list` 确认：

```bash
claude mcp list
# github  → https://api.githubcopilot.com/mcp  (http)
# gem5    → python3 tools/mcp/gem5_mcp/server.py (stdio)
```

### 方式二：`claude mcp add`（用户级）

```bash
# GitHub（远程 HTTP + PAT）
claude mcp add-json github '{"type":"http","url":"https://api.githubcopilot.com/mcp","headers":{"Authorization":"Bearer '$GITHUB_PERSONAL_ACCESS_TOKEN'"}}'

# gem5（本地 stdio）
claude mcp add gem5 -- python3 tools/mcp/gem5_mcp/server.py
```

> 无网络远程模式时，可用官方 Docker 镜像替代 GitHub server（需 Docker + PAT）：
> `claude mcp add github -e GITHUB_PERSONAL_ACCESS_TOKEN -- docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN ghcr.io/github/github-mcp-server`

## 工具参考

| 工具 | 参数 | 说明 |
|---|---|---|
| `gem5_build` | `isa="X86"`, `jobs=0`, `timeout=3600` | `scons build/{isa}/gem5.opt -j {jobs}`；`jobs=0` 取 `os.cpu_count()` |
| `gem5_simulate` | `config="tools/mcp/configs/x86-hello.py"`, `timeout=900` | `./build/X86/gem5.opt <config>`；相对路径相对仓库根解析 |
| `gem5_status` | 无 | 报告二进制是否存在、m5out 内容、`stats.txt` 关键指标 |

所有工具都在仓库根执行（仓库根由 `GEM5_ROOT` 环境变量或 `server.py` 相对位置解析）。
长任务的 stdout/stderr 通过 MCP 进度日志流式回传（每 100 行一条），返回时附末 120 行尾部。

## 验证（端到端）

```bash
# 1) 依赖
python3 -c "import mcp; print(mcp.__version__)"

# 2) 工具注册（本地直接调 server.py，Ctrl-C 退出；或 MCP Inspector）
python3 tools/mcp/gem5_mcp/server.py

# 3) 编译（首次约 20–60 分钟，产物 build/X86/gem5.opt）
scons build/X86/gem5.opt -j$(nproc)

# 4) 仿真（首次会下载 x86-hello64-static 资源）
./build/X86/gem5.opt tools/mcp/configs/x86-hello.py
# 期望：m5out/stats.txt 出现 simTicks，stdout 打印 "Hello world!"
```

## 常见问题

- **`claude mcp get github` 报 `✘ Failed to connect`**：PAT 未设置或权限不足；
  先 `export GITHUB_PERSONAL_ACCESS_TOKEN=...` 再重启 Claude Code。
- **远程 HTTP 模式要求 Claude Code ≥ 2.1.1**；更老版本用 Docker 模式或升级。
- **首次 `gem5_build` 慢**：gem5 全量编译约 20–60 分钟，属正常；
  若缺 `protoc`（`which protoc` 无输出）先 `apt install protobuf-compiler`。
- **`mcp` 装成 2.0 报 `No module named 'mcp.server.fastmcp'`**：按上述 `requirements.txt` 装 1.x。
- **构建报 `error while loading shared libraries: libpython3.x.so` / `Can't find a working Python installation`**：
  gem5 会嵌入 `python3-config` 指向的那个 Python。若 PATH 里是 miniconda 3.13，其
  `libpython3.13.so` 不在动态链接器默认路径，且版本过新（gem5 支持 3.8–3.12）。
  `gem5_build` 默认已把 `/usr/bin` 前置到 PATH 用系统 Python（如 3.10）构建；
  如需自定义，设 `GEM5_BUILD_PATH_PREFIX` 环境变量。手工构建等价命令：
  `env PATH="/usr/bin:/bin:$PATH" scons build/X86/gem5.opt -j$(nproc)`。
