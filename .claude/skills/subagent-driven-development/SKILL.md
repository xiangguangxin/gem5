---
name: subagent-driven-development
description: 用多个子 Agent 拆分复杂开发任务（设计/实现/对抗评审/验证）。当任务规模大、适合并行分工时使用。具体子 Agent 定义见 .claude/agents/。
---

# Subagent Driven Development

用 Claude Code 原生 subagent 驱动开发。团队由 `.claude/agents/*.md` 定义。

## 团队构成

| 角色 | subagent_type | 职责 | 工具 |
|---|---|---|---|
| 架构师 | `cto` | 需求分析 → 架构方案 + 任务清单 | 只读 + 搜索 |
| 对抗评审 | `red-team` | 攻击架构/代码，找缺陷与失败模式（证伪） | 只读 + Bash |
| 文档 | `tech-writer` | 架构方案 → 设计文档 | 读写文档 |
| 开发 | `developer` | 设计 → 代码 + 单测（TDD） | 读写 + Bash |
| 验证/评审 | `verifier` | 跑 build/测试 + 评审 → 证据（证实） | 读 + Bash |

## 协作流程

```
需求
  ↓
[cto]           → 架构方案 + 任务清单
  ↓
[red-team]      → 攻击架构 → 缺陷清单 → 回 [cto] 修订      ← 闸门1（设计）
  ↓
[tech-writer]   → 设计文档（docs/）
  ↓
[developer]     → 代码 + 单测
  ↓
[red-team]      → 攻击代码 → 缺陷清单 → 回 [developer] 修复 ← 闸门2（实现）
  ↓
[verifier]      → 跑 build/测试 + 评审 → 证据（证实）
  ↓
  失败 → 把问题清单交回 [developer] 修复
  通过 → finish-development-branch 收尾
```

## 对抗闸门（red-team）

red-team 是**证伪**者，verifier 是**证实**者，别混淆：
- red-team 找"哪里可能坏、怎么坏"，产出缺陷清单，不下"对不对"的结论。
- verifier 跑真实测试，下"通过/不通过" + 证据。

**触发条件（满足任一条就审）：**

1. 接口/契约变更：改函数签名、公共头文件、数据结构、被多模块 import 的接口。
2. 高风险语义：并发/锁/竞态、内存安全、指针/缓冲区、时序、状态机、边界/溢出。
3. 架构级决定：新增模块划分、跨模块依赖、技术选型、协议/格式定义。
4. 规模：单次 diff > 阈值（如 200 行或 5 文件），或跨多模块。
5. 全新无参照：没有现成模式可抄的新实现。

**默认审，跳过要理由**：拿不准就审。跳过必须写一句可查的理由（如"纯格式/机械复制/秒回退"），不能默认跳过。

**回灌闭合**：red-team 列的每个缺陷，要么被修复，要么明确"接受风险"，不能列了不管。

## 调用方式

用 Agent 工具按依赖顺序 spawn 上述 subagent_type：

1. `Agent(subagent_type: "cto", ...)` → 架构方案。
2. 触发闸门则 `Agent(subagent_type: "red-team", ...)` 攻击架构 → 缺陷回给 cto 修订。
3. 架构方案交给 `tech-writer` → 设计文档。
4. 设计文档交给 `developer` → 代码 + 单测。
5. 触发闸门则 `Agent(subagent_type: "red-team", ...)` 攻击代码 → 缺陷回给 developer 修复。
6. 设计文档 + 代码交给 `verifier` → 验证报告。
7. verifier 说"不通过"时，问题清单交回 developer 修复，回到第 6 步；通过则 finish-development-branch 收尾。

## 交接物

- `cto` → 架构方案（含任务清单 + 待决策 + 风险）
- `red-team` → 缺陷清单（现象 → 触发条件 → 为什么错 → 建议，按严重度排序）
- `tech-writer` → 设计文档（接口具体到可编码）
- `developer` → 代码 + 单测（build/测试通过）
- `verifier` → 验证报告（含真实运行输出 + 评审结论）

## 验证门禁

- verifier 说"通过"之前，不得宣布完成（verification-before-completion）。
- 失败必须回环修复，不允许跳过验证直接交付。
- 每个 agent 的输出必须被下游真实消费，不允许出现"产出物无人用"。
