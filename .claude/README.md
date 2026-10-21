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
├── skills/          # 可被 Claude Code 加载的标准 skill（<名字>/SKILL.md）
├── workflows/       # 确定性编排脚本（agent-team.js，内置审核闸门）
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

编排协议详见 [skills/subagent-driven-development/SKILL.md](skills/subagent-driven-development/SKILL.md)。确定性编排（硬性审核闸门）见 [workflows/agent-team.js](workflows/agent-team.js)。

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
