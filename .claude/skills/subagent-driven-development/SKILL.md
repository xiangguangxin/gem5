---
name: subagent-driven-development
description: 用多个子 Agent 拆分复杂开发任务（设计/实现/测试/评审）。当任务规模大、适合并行分工时使用。具体子 Agent 定义见 .claude/agents/。
---

# Subagent Driven Development

用 Claude Code 原生 subagent 驱动开发。团队由 `.claude/agents/*.md` 定义。

## 团队构成

| 角色 | subagent_type | 职责 | 工具 |
|---|---|---|---|
| 架构师 | `cto` | 需求分析 → 架构方案 + 任务清单 | 只读 + 搜索 |
| 文档 | `tech-writer` | 架构方案 → 设计文档 | 读写文档 |
| 开发 | `developer` | 设计 → 代码 + 单测（TDD） | 读写 + Bash |
| 验证/评审 | `verifier` | 跑 build/测试 + 评审 → 证据 | 读 + Bash |

## 协作流程

```
需求
  ↓
[cto]          → 架构方案 + 任务清单
  ↓
[tech-writer]  → 设计文档（写到 docs/）
  ↓
[developer]    → 代码 + 单测
  ↓
[verifier]     → 跑 build/测试 + 评审 → 证据报告
  ↓
  失败 → 把问题清单交回 [developer] 修复
  通过 → finish-development-branch 收尾
```

## 调用方式

用 Agent 工具按依赖顺序 spawn 上述 subagent_type：

1. `Agent(subagent_type: "cto", prompt: "分析需求：<需求>")` → 拿到架构方案。
2. 把架构方案交给 `tech-writer` → 设计文档。
3. 把设计文档交给 `developer` → 实现代码 + 单测。
4. 把设计文档 + 代码交给 `verifier` → 验证报告。
5. verifier 说"不通过"时，把它列的问题清单交回 `developer` 修复，再回到第 4 步；通过则用 `finish-development-branch` 收尾。

## 交接物

- `cto` → 架构方案（markdown，含任务清单 + 待决策 + 风险）
- `tech-writer` → 设计文档（写到 `docs/`，接口具体到可编码）
- `developer` → 代码 + 单测（build/测试通过）
- `verifier` → 验证报告（含真实运行输出 + 评审结论）

## 验证门禁

- verifier 说"通过"之前，**不得宣布完成**（verification-before-completion）。
- 失败必须回环修复，不允许跳过验证直接交付。
- 每个 agent 的输出必须被下游真实消费，不允许出现"产出物无人用"。
