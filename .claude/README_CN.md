# Superpowers 中文版 Skill 文档库

本目录按照 Superpowers 的思想整理中文工程化文档。

目标：

让 AI Coding Agent 按照软件工程流程工作：

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
├── skills/          # 可被 Claude Code 加载的标准 skill（<名字>/SKILL.md）
├── examples/        # 工程化示例（AUTOSAR / SystemC）
├── templates/       # Prompt 模板
└── README_CN.md     # 本索引
```

## 开发流程 Skill 索引

按执行顺序：

| # | Skill 目录 | 作用 |
|---|---|---|
| 01 | brainstorming | 需求探索——编码前澄清目标、约束与验证方式 |
| 02 | writing-plans | 实施计划——把设计拆解为可执行任务 |
| 03 | executing-plans | 执行计划——小步执行、小步验证 |
| 04 | subagent-driven-development | 子 Agent 驱动开发——拆分复杂任务 |
| 05 | test-driven-development | 测试驱动开发——RED / GREEN / REFACTOR |
| 06 | systematic-debugging | 系统化调试——证据驱动定位根因 |
| 07 | requesting-code-review | 代码审查——需求 / 架构 / 边界 / 测试 / 规范 |
| 08 | verification-before-completion | 完成前验证——交付前提供证据 |
| 09 | git-worktrees | 多工作区——多任务并行独立环境 |
| 10 | finish-development-branch | 完成开发分支——收尾、整理 Commit、Merge |

其它：

| Skill 目录 | 作用 |
|---|---|
| grilling | 架构压力测试——对设计持续追问与推演 |
