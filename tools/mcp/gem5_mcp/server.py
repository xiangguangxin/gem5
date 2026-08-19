"""gem5 MCP server.

Provides three tools for driving a gem5 checkout from an MCP client:

- ``gem5_build``     — run ``scons build/<isa>/gem5.opt -j <jobs>``.
- ``gem5_simulate``  — run ``./build/X86/gem5.opt <config>`` (SE mode).
- ``gem5_status``    — report whether the binary / m5out artifacts exist.

All subprocesses run from the repository root, resolved as (in order of
precedence):

1. the ``GEM5_ROOT`` environment variable, or
2. three directories above this file (``tools/mcp/gem5_mcp/server.py``).
"""

from __future__ import annotations

import asyncio
import os
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

SERVER_NAME = "gem5"
REPO_ROOT = Path(os.environ.get("GEM5_ROOT", Path(__file__).resolve().parents[3]))
BUILD_ISA = "X86"
DEFAULT_CONFIG = "tools/mcp/configs/x86-hello.py"
TAIL_LINES = 200          # rolling buffer size kept in memory
RETURN_TAIL = 120         # how many tail lines are returned to the client
REPORT_EVERY = 100        # emit a progress log every N output lines

# Guard against path / argument injection: an ISA name must be a bare token.
_ISA_RE = re.compile(r"^[A-Za-z0-9_]+$")

mcp = FastMCP(SERVER_NAME)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _resolve_config(config: str) -> Path:
    """Resolve a config script path against the repo root.

    Absolute paths are used as-is (allows user-owned scripts); relative paths
    are resolved under ``REPO_ROOT``.
    """
    p = Path(config)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p.resolve()


def _build_env() -> dict[str, str]:
    """Return the subprocess environment used for the scons build.

    gem5 embeds whichever Python ``python3-config`` points at (see
    ``SConstruct`` ``PYTHON_CONFIG``). A non-system interpreter (e.g. miniconda
    3.13) puts ``libpython*.so`` outside the dynamic linker's default search
    path, so the configure step fails with ``cannot open shared object file``.
    Prepend ``/usr/bin`` (and ``/bin``) to ``PATH`` so the build uses the
    system Python (e.g. 3.10, a supported gem5 version). Override the prefix
    via the ``GEM5_BUILD_PATH_PREFIX`` environment variable if needed.
    """
    env = os.environ.copy()
    prefix = os.environ.get("GEM5_BUILD_PATH_PREFIX", "/usr/bin:/bin")
    env["PATH"] = f"{prefix}:{env.get('PATH', '')}"
    return env


async def _run_streaming(
    cmd: list[str],
    cwd: Path,
    timeout: int,
    ctx: Context,
    tag: str,
    env: dict[str, str] | None = None,
) -> str:
    """Run a command, stream its output as progress logs, return a summary.

    The full output is never buffered in memory; only a bounded rolling tail
    is kept. On success or failure the tail is returned so the caller can
    inspect the outcome (and, on failure, locate the root cause).
    """
    start = datetime.now(timezone.utc)
    await ctx.info(f"[{tag}] $ {' '.join(cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env=env,
    )

    tail: deque[str] = deque(maxlen=TAIL_LINES)
    total_lines = 0
    last_report = 0

    async def pump() -> None:
        nonlocal total_lines, last_report
        assert proc.stdout is not None
        async for raw in proc.stdout:
            text = raw.decode(errors="replace").rstrip("\n")
            total_lines += 1
            tail.append(text)
            if total_lines - last_report >= REPORT_EVERY:
                last_report = total_lines
                await ctx.info(f"[{tag}] … {total_lines} 行输出，最近：{text}")

    timed_out = False
    try:
        await asyncio.wait_for(pump(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        await ctx.info(f"[{tag}] 超时（>{timeout}s），正在终止进程")
        proc.kill()

    return_code = await proc.wait()
    elapsed = (datetime.now(timezone.utc) - start).total_seconds()

    lines = list(tail)
    shown = lines[-RETURN_TAIL:]
    tail_text = "\n".join(shown)
    if total_lines > len(shown):
        tail_text = f"…(截断，共 {total_lines} 行，仅显示末 {len(shown)} 行)…\n{tail_text}"

    status = "超时被杀" if timed_out else f"exit_code={return_code}"
    summary = (
        f"[{tag}] 完成：{status}，耗时 {elapsed:.1f}s，输出 {total_lines} 行\n"
        f"--- 输出尾部 ---\n{tail_text}"
    )
    return summary


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #


@mcp.tool()
async def gem5_build(
    ctx: Context,
    isa: str = BUILD_ISA,
    jobs: int = 0,
    timeout: int = 3600,
) -> str:
    """编译 gem5 二进制（默认 X86 标准构建）。

    Args:
        isa: 目标 ISA（对应 build_opts/ 下的配置），默认 "X86"。
        jobs: 并行编译线程数，0 表示用 `os.cpu_count()`。
        timeout: 超时秒数，默认 3600（首次完整构建可能需 20–60 分钟）。
    """
    if not _ISA_RE.match(isa):
        return f"非法 ISA 名：{isa!r}（仅允许字母/数字/下划线）"

    if jobs <= 0:
        jobs = os.cpu_count() or 1

    binary = REPO_ROOT / "build" / isa / "gem5.opt"
    cmd = ["scons", f"build/{isa}/gem5.opt", f"-j{jobs}"]
    return await _run_streaming(cmd, REPO_ROOT, timeout, ctx, f"build:{isa}", env=_build_env())


@mcp.tool()
async def gem5_simulate(
    ctx: Context,
    config: str = DEFAULT_CONFIG,
    timeout: int = 900,
) -> str:
    """运行 gem5 SE 仿真（默认 X86 + x86-hello64-static 最小脚本）。

    Args:
        config: gem5 配置脚本路径，默认 tools/mcp/configs/x86-hello.py。
            绝对路径按原样使用；相对路径相对仓库根解析。
        timeout: 超时秒数，默认 900（首次运行会下载 workload 资源）。
    """
    binary = REPO_ROOT / "build" / BUILD_ISA / "gem5.opt"
    if not binary.is_file():
        return (
            f"未找到二进制 {binary}。请先调用 gem5_build 编译，"
            f"或检查 build/{BUILD_ISA}/gem5.opt 是否已生成。"
        )

    config_path = _resolve_config(config)
    if not config_path.is_file():
        return f"配置脚本不存在：{config_path}"

    cmd = [str(binary), str(config_path)]
    return await _run_streaming(cmd, REPO_ROOT, timeout, ctx, "simulate")


@mcp.tool()
async def gem5_status(ctx: Context) -> str:
    """报告 gem5 构建产物与 m5out 仿真输出的状态。"""
    lines: list[str] = []
    binary = REPO_ROOT / "build" / BUILD_ISA / "gem5.opt"

    lines.append(f"仓库根目录：{REPO_ROOT}")

    if binary.is_file():
        st = binary.stat()
        mtime = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        lines.append(
            f"二进制：存在 {binary}（{st.st_size / 1e6:.1f} MB，"
            f"mtime {mtime.isoformat(timespec='seconds')}）"
        )
    else:
        lines.append(f"二进制：不存在（{binary}）——请先 gem5_build")

    m5out = REPO_ROOT / "m5out"
    if m5out.is_dir():
        entries = sorted(p.name for p in m5out.iterdir())
        lines.append(f"m5out：{entries if entries else '（空）'}")
        stats = m5out / "stats.txt"
        if stats.is_file():
            # Pull a few headline numbers out of stats.txt for a quick glance.
            for key in ("simTicks", "simSeconds", "hostSeconds", "simInsts"):
                m = re.search(rf"^{re.escape(key)}\s+([0-9.eE+-]+)\s+.*$", stats.read_text(), re.M)
                if m:
                    lines.append(f"  stats: {key} = {m.group(1)}")
    else:
        lines.append("m5out：不存在（尚未运行仿真）")

    return "\n".join(lines)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
