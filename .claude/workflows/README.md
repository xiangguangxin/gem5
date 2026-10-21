# 可执行的 Codex 客户端闭环

`codex-team.py` 是本仓库的第一个真实客户端适配器，使用 Python 标准库调用已经安装并登录的 Codex CLI，不需要 Node 或另配 API SDK。

## 运行链路

```text
任务 JSON → 主进程采集基线与初始指纹 → cto → red-team 设计评审 → tech-writer
    → developer → red-team 实现评审
    → 主进程执行验收命令 → verifier
    → 主进程再次验收与文件范围检查 → verified
```

各角色是独立、顺序启动的 `codex exec --ephemeral` 会话，沿用当前客户端模型配置；不硬编码模型。角色提示读取 `.claude/agents/*.md` 和协作契约，不意味着 Codex 原生解析 Claude 的角色工具白名单。只读角色使用 read-only，文档/开发角色使用 workspace-write；没有使用跳过审批和沙箱的参数。

评审、输出格式、退出码或超时异常会停止；架构或实现需要修订时在最多三轮内回交，仍失败则停止并保留现场。不会自动安装依赖、提交、推送或合并，也不自动启动嵌套 Agent。

## 准备条件

```bash
codex --version
codex login status
python3 --version
```

需支持 exec、--ephemeral、--output-schema、-o 和相应 sandbox 的 Codex CLI。实际参数以当前安装版本 help 为准。首次客户端使用的登录与安装需要独立完成，本运行器不修改客户端全局配置。

## 先用独立 fixture 验收

仓库中的示例函数故意写错，**不要在示例源目录直接修复**。复制到临时工作区后运行：

```bash
harness_example=$(mktemp -d /tmp/gem5-harness-example-XXXXXX)
cp -R .claude/workflows/examples/cache-address-fixture "$harness_example/workspace"
python3 .claude/workflows/codex-team.py \
  --task .claude/workflows/examples/cache-address-task.json \
  --workspace "$harness_example/workspace" \
  --output "$harness_example/run" \
  --timeout 240 --rounds 3
```

预期 developer 修复地址拆分与输入校验，tech-writer 写 DESIGN.md，原始测试保持不变。最终进程退出 0、state.json 的 done=true/status=verified，且 final_checks 中所有退出码为 0，才算本次闭环成功。

每次执行会消耗真实客户端额度；不要把这个命令放进普通单元测试或无条件 CI。已有项目应先在可丢弃工作树中试用。

## 自定义任务

任务包含 requirement、scope、acceptance、checks：

- scope：允许修改的明确相对文件名，不支持目录通配；含新文档时也列出其名称。
- acceptance：用户认可的验收要求，逐角色保留。
- checks：可信任务提供的命令 argv 数组，例如 `["python3", "-m", "unittest", "-v", "test_example.py"]`，主进程不通过 shell 执行。
- 验收命令应不修改工作区，不能自动安装依赖或访问生产系统。

**checks 会以主进程权限执行，必须来自可信任务定义；argv 不使用 shell 不等于命令安全。** scope 是执行后检测，不是逐文件写入访问控制，范围外变更会停止但不自动撤销；不要在有价值的共享目录中把它当成完整隔离。沙箱、用户级配置、hooks 和 MCP 以客户端实际环境为准。

输出目录必须在工作区之外且事先不存在，防止覆盖记录。目录不能含符号链接；当前实现面向小型独立工作区，会扫描全部工作区文件（包括 Git 元数据），暂不适合直接对整个大型 gem5 树逐阶段快照。

## 产物与失败定位

输出目录保留：

| 文件 | 含义 |
|---|---|
| state.json | 当前状态、初始/最终文件 SHA-256、修复前基线、阶段历史与最终验收 |
| NN-phase.prompt.txt | 该角色收到的任务包及交接 |
| NN-phase.result.json | 客户端最终结构化响应 |
| NN-phase.stdout/stderr.log | 客户端运行日志 |
| baseline-checks.json / round-N-checks.json / final-checks.json | 主进程真实验收命令、退出码与关键输出 |

日志可能含源码或环境相关信息，发布前人工审查。客户端错误或超时时不会当作通过；超时/中断会终止本次进程组，保留工作区供检查。state 记录用于审计，当前**没有断点自动恢复**；不要直接用同一 output 重跑，也不要误称可续跑。

## 运行器回归测试

不调用模型的自动测试：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s .claude/workflows/tests -p 'test_codex_team.py' -v
```

覆盖输入和输出校验、越界修改、日志位置、失败验收阻断、客户端错误、验收修改工作区和超时。包含基线失败→修复后成功→独立验证交接的证据链回归。这些测试与真实客户端验收分开报告。

原有 `agent-team.js` 仍是 JavaScript 宿主模板，没有自动套用 Python 适配器。两者使用相同团队原则，但不是共享实现；修改后各自运行回归，不能用一个的结果证明另一个正确。

## 官方依据

- [Codex 非交互执行](https://developers.openai.com/codex/noninteractive)
- [使用 Codex 构建修复循环](https://developers.openai.com/cookbook/examples/codex/build_iterative_repair_loops_with_codex)

本实现同时核对了实际客户端的 `codex exec --help`；真实验收见 [2026-10-21 Codex 闭环报告](evidence/2026-10-21-codex/README.md)。
