---
name: brainstorming
description: 需求探索——在编码前先澄清目标、约束、已有架构与验证方式，而不是直接写代码。当用户提出新功能、需求模糊，或需要先理解真实问题再动手时使用。
---

# Brainstorming

## 需求探索 Skill

目标：

在开始编码前理解真实问题。

流程：

需求 -> 澄清问题 -> 分析约束 -> 比较方案 -> 确认设计

AI 不应该立即输出代码，而应该先确认：

-   目标是什么
-   限制条件是什么
-   是否存在已有架构
-   如何验证结果

工程示例：

实现 AUTOSAR Eth Driver 时，需要先确认：

-   Buffer ownership
-   Interrupt/Polling模式
-   Controller状态
-   SIL是否模拟硬件行为
