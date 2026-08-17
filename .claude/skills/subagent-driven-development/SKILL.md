---
name: subagent-driven-development
description: 用多个子 Agent 拆分复杂开发任务（设计/实现/测试/评审）。当任务规模大、适合并行分工时使用。
---

# Subagent Driven Development

## 子Agent驱动开发

复杂任务拆分：

-   Design Agent
-   Implementation Agent
-   Test Agent
-   Review Agent

适合：

-   大型软件
-   芯片模型
-   驱动开发
-   性能模型开发

示例：

NPU Performance Model：

设计Agent负责模型设计。

实现Agent负责C++实现。

测试Agent负责benchmark。
