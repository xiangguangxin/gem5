# Part 3 · 第 1 章：Ruby、SLICC 与 MSI 协议概述

> 对应源码：`src/learning_gem5/part3/`（MSI.slicc / MSI-msg.sm / MSI-cache.sm / MSI-dir.sm）
> 配置脚本：`configs/learning_gem5/part3/`

## 本章目标

理解 gem5 的 **Ruby** 一致性子系统，用 **SLICC** 语言描述缓存一致性协议，
以 **MSI** 协议为例走通完整流程。

## 两个内存子系统：classic vs Ruby

gem5 有**两套**缓存/内存模型：

| | classic | Ruby |
|--|---------|------|
| 缓存模型 | 手工搭（part1/part2 的 Cache/SimpleCache） | 控制器 + 网络 + 消息 |
| 一致性 | 简单、单点 | 支持任意协议（MESI/MOESI/MSI…） |
| 适用 | 单核、简单多核 | 研究一致性协议、互联网络 |

Ruby 的核心思想：系统由一组 **controller**（L1 缓存、目录、内存控制器）组成，
它们通过 **network** 互相发**消息**来维护一致性。

## SLICC 是什么

**SLICC** = Specification Language for Implementing Cache Coherence。
一种写一致性协议状态机的 **DSL**，编译时被转成 C++ 类（如 `MSI_L1Cache_Controller`）。

## MSI 协议的文件结构

```
MSI.slicc         协议顶层：声明协议名 + include 下面 3 个 .sm
  ├─ MSI-msg.sm   消息类型（枚举 + 消息结构体）
  ├─ MSI-cache.sm L1 缓存控制器状态机（CPU 侧）
  └─ MSI-dir.sm   目录控制器状态机（内存侧）
```

```slicc
// MSI.slicc
protocol "MSI";
include "MSI-msg.sm";
include "MSI-cache.sm";
include "MSI-dir.sm";
```

## MSI 的三大稳定状态

MSI 是最经典的一致性协议（源自 Sorin et al. 《A Primer on Memory Consistency
and Cache Coherence》第 8 章）：

| 状态 | 含义 | 权限 |
|------|------|------|
| **I** (Invalid) | 块不在本缓存 | 无 |
| **S** (Shared) | 只读，多个缓存可能有同一份 | 只读 |
| **M** (Modified) | 可读写，本缓存是唯一 owner | 读写 |

除了这 3 个**稳定状态**，还有一堆**瞬态状态**（名字带下划线，如 `IS_D`），
表示「正在从一个稳定态迁移到另一个稳定态、还在等消息」的中间态。

## 消息类型（MSI-msg.sm）

```slicc
enumeration(CoherenceRequestType, ...) {   // cache → dir / dir → cache
    GetS,    // 请求只读权限
    GetM,    // 请求读写权限
    PutS,    // S 态逐出（clean）
    PutM,    // M 态逐出（dirty，写回）
    Inv,     // 目录发给缓存：失效请求
    PutAck,  // 目录确认收到 put
}
enumeration(CoherenceResponseType, ...) {
    Data,    // 带最新数据的响应
    InvAck,  // 其他缓存确认已失效
}
```

## 三个虚拟网络（virtual network，防死锁）

MSI 用 3 个 vnet，**优先级从高到低**：

| vnet | 名称 | 内容 | 优先级 |
|------|------|------|--------|
| 0 | request | cache→dir 的请求 | 最低 |
| 1 | forward | dir→cache 的转发（fwd/inv/putack） | 中 |
| 2 | response | 响应 | 最高 |

为什么分 vnet：**避免死锁**——响应不能被卡在请求后面。高优先级的响应网络
永远能先走，不会因为低优先级请求占满缓冲区而饿死。

## SLICC 语法骨架（先有个印象，后续章节展开）

```slicc
machine(MachineType:L1Cache, "MSI cache")
    : Sequencer *sequencer;       // 机器参数（从 Python 配置注入）
      MessageBuffer * requestToDir, network="To", virtual_network="0", ...;
{
    state_declaration(State, ...) { I, S, M, ... }   // 状态
    enumeration(Event, ...) { Load, Store, ... }      // 事件
    structure(Entry, interface="AbstractCacheEntry", ...) { ... }  // 块结构
    transition(I, Load, IS_D) { ... }                  // 迁移 + 动作
}
```

- `machine(...)`：声明一个控制器（状态机）。
- `state_declaration`：稳定态 + 瞬态（带下划线）。
- `enumeration(Event, ...)`：触发状态迁移的事件。
- `transition(当前态, 事件, 目标态)`：核心——状态 × 事件 → 新状态 + 动作。
