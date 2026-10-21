# AI 工程团队 — Claude Code 原生 Subagent + Skill 库

本目录按照 Superpowers 的思想，让 AI Coding Agent 按软件工程流程工作：

需求分析 -> 设计 -> 计划 -> 实现 -> 测试 -> Review -> 交付

核心理念：

-   Design First
-   Test Driven Development
-   Systematic Debugging
-   Evidence Before Completion
-   Small Incremental Changes

---

## 目录结构

```
.claude/
├── agents/          # Claude Code 原生 subagent（cto / red-team / tech-writer / developer / verifier）
├── skills/          # 项目技能（<名字>/SKILL.md）
├── references/      # 团队协作契约
├── integrations/    # 可选工具接入与来源说明
├── workflows/       # 宿主编排模板与模拟测试（不自带 Agent 执行器）
└── README.md        # 本索引
```

## Agent 团队

`.claude/agents/*.md` 定义了 5 个 Claude Code 原生 subagent，由 `subagent-driven-development` skill 编排协作：

| 角色 | subagent_type | 职责 |
|---|---|---|
| 架构师 | `cto` | 需求分析 → 架构方案 + 任务清单 |
| 对抗评审 | `red-team` | 攻击架构/代码，找缺陷与失败模式（证伪） |
| 文档 | `tech-writer` | 架构方案 → 设计文档 |
| 开发 | `developer` | 设计 → 代码 + 单测（TDD） |
| 验证/评审 | `verifier` | 跑 build/测试 + 评审 → 证据（证实） |

协作流程：

```
Requirement
    |
    v
[cto]            → 架构方案 + 任务清单
    |
    v
[red-team]       → 攻击架构 → 缺陷 → 回 [cto] 修订
    |
    v
[tech-writer]    → 设计文档（docs/）
    |
    v
[developer]      → 代码 + 单测
    |
    v
[red-team]       → 攻击代码 → 缺陷 → 回 [developer] 修复
    |
    v
[verifier]       → build/测试 + 评审 → 证据
    |
    +-- fail --> 回 [developer] 修复
    +-- pass --> finish-development-branch 收尾
```

编排协议详见 [skills/subagent-driven-development/SKILL.md](skills/subagent-driven-development/SKILL.md)。可选宿主编排模板（结果门禁）见 [workflows/agent-team.js](workflows/agent-team.js)。

---

## 开发流程 Skill 索引

按执行顺序：

| # | Skill 目录 | 作用 |
|---|---|---|
| 01 | brainstorming | 需求探索——编码前澄清目标、约束与验证方式 |
| 02 | writing-plans | 实施计划——把设计拆解为可执行任务 |
| 03 | executing-plans | 执行计划——小步执行、小步验证 |
| 04 | subagent-driven-development | 子 Agent 驱动开发——拆分复杂任务 |
| 05 | test-driven-development | 测试驱动开发——RED / GREEN / REFACTOR |
| 06 | bug-fix | 系统化修复——复现 → 根因 → 影响 → 修复 → 回归 |
| 07 | requesting-code-review | 代码审查——需求 / 架构 / 边界 / 测试 / 规范 |
| 08 | verification-before-completion | 完成前验证——交付前提供证据 |
| 09 | git-worktrees | 多工作区——多任务并行独立环境 |
| 10 | finish-development-branch | 完成开发分支——收尾、整理 Commit、Merge |

其它：

| Skill 目录 | 作用 |
|---|---|
| grilling | 架构压力测试——对设计持续追问与推演 |


## 技术文档绘图 Skill

[technical-diagrams](skills/technical-diagrams/SKILL.md) 用于架构图、指针图、状态图和时序图：按用途选择 Mermaid、原生 SVG 或可选 D2，保留可维护源文件，检查后嵌入 Markdown。

- [工具选择与本地命令](skills/technical-diagrams/references/tools.md)
- [SVG 风格模板](skills/technical-diagrams/assets/diagram-template.svg)
- [SVG 基础检查脚本](skills/technical-diagrams/scripts/check_svg.py)

调用示例：`使用 .claude/skills/technical-diagrams/SKILL.md，为 nextBin/nextInBin 画 SVG 指针图并插入笔记。`

默认本地执行，无需在线账号；没有安装 D2/Mermaid CLI 也可直接写 SVG。外部画布插件不是必选依赖。这里创建的是仓库级技能文件，不等于已安装软件或已在所有 Agent 客户端全局启用。


此技能已在仓库根目录 CLAUDE.md 中设为技术文档的默认配图流程：适合用图说明时自动采用，不要求每篇都画图。现有文档修改保留所在路径；提交、推送和工具安装仍按用户授权执行。


## REA：按需二进制与应用分析

已整合 [reverse-engineer-anything 官方 Skill](skills/reverse-engineer-anything/SKILL.md) 及配套参考，来源、固定提交、MIT 许可和环境状态见 [REA 项目集成说明](integrations/rea/README.md)。

- 用途：无源码二进制、交付包、请求范围内的运行时行为分析。
- 普通 gem5 C++/SLICC 源码解释仍使用仓库阅读流程，图形输出交给 technical-diagrams。
- 本地环境检查：`python3 .claude/integrations/rea/check_environment.py`。
- Skill 文件已纳入仓库，不代表 Node、分析引擎或 MCP 已安装连接。项目 local-scope 接入方式见集成说明，不自动改全局客户端设置。

## 团队协作的执行约定

[team-contract.md](references/team-contract.md) 统一任务输入、角色边界、交接格式、P0～P3 问题分级、修复回环和分级验证。角色不是字数越多越好：每次任务必须给出上下文、文件范围和验收，下游必须实际使用上游产物。

现有 agent-team.js 是需要宿主注入 agent/args/log 的流程模板，不是独立启动器；现另有 [Codex CLI 执行适配器](workflows/README.md)，可在独立工作区运行真实闭环；JS 模板自身仍不自带宿主。它现在对空评审、无证据验证及架构评审超限拒绝放行；脚本不能替代真实执行证据。模拟测试：`node .claude/workflows/tests/agent-team.test.mjs`。

简单文档任务走相应角色和检查，不机械触发五角色完整链路。没有独立 Agent 能力时说明顺序执行，不能把提示文件存在说成团队已经运行。提交与远程推送仍遵循用户授权。


## 真实客户端任务闭环

[workflows/codex-team.py](workflows/codex-team.py) 使用已登录的 Codex CLI 顺序运行五角色，保存结构化报告和日志，并由主进程独立执行任务验收。包含可复制的故障 fixture 和无需模型的回归测试。运行、权限边界及限制见 [使用说明](workflows/README.md)。

真实运行证据：[2026-10-21 Codex 闭环验收](workflows/evidence/2026-10-21-codex/README.md)，包含失败基线、最终通过输出、文件指纹与修复补丁。


## 有证据的项目记忆

[project-memory Skill](skills/project-memory/SKILL.md) 管理事实、设计决策和经验的候选提炼、证据核对与评审入库。存储格式、生命周期和操作见 [记忆指南](memory/README.md)。Codex Harness 已接入有界检索、阶段检查点与成功运行的字段级事实采集，可用 --no-memory 关闭。语义经验仍需提议和评审，不自动改写核心规则。
