# Garnet 入门：NI、Router、VC、Credit 与背压怎样协作

> 本文将这些机制放在同一条消息路径中讲解，重点回答“数据放在哪里、谁决定发送、为什么停下来、又如何恢复”。实现依据当前仓库 Garnet；例子用于解释原理，未执行仿真。

## 1. 先看一条完整路径

假设源控制器要给目标控制器发送消息，中间经过三个 Router，分别称为 A、B、C：

```text
源控制器 → 发送 MessageBuffer → 源 NI
 → Router A → Router B → Router C
 → 目标 NI → 接收 MessageBuffer → 目标控制器
```

A、B、C 是 Router 的简称，不是 CPU 或控制器。各箭头所表示的网络连接通过 NetworkLink 传输 flit，并配有相反方向的 CreditLink 反馈。

Ruby 控制器产生 GetM、Data 等协议消息。Garnet 的 NI、Router 和链路负责消息传输，接收控制器再处理协议状态转换。当前教学 MSI 默认仍使用 SimpleNetwork；本文解释的是 Garnet 路径。

## 2. 先认识 Message、Packet 和 Flit

Message 表达协议含义，例如“将地址 X 的最新数据返回 Cache0”。单目标消息在网络中形成一个包 Packet，包再拆成一个或多个 Flit。多目标消息会先按目标拆成多个单播包。

Flit 是缓冲、链路传输和流控的基本单位。假设数据消息建模大小 72B，flit 宽度 16B，则需要 ceil(72/16)=5 个 flit：

```text
Packet P：[HEAD][BODY][BODY][BODY][TAIL]
```

HEAD 是包头，建立当前跳的输出方向和 VC 关联；BODY 沿用这些关联；TAIL 标记包结束。一个 flit 就能装下的包使用 HEAD_TAIL。

本模拟实现的 flit 保存消息引用和路由等元数据，不是将 C++ 消息对象按 sizeof 切成字节数组。flit 数依据消息类别映射的建模大小计算。

## 3. NetworkInterface：控制器接入网络的接口

### 3.1 发送侧

NI 的一端连接协议 MessageBuffer，另一端通过链路连接 Router。它从指定 VNet 的发送队列读取就绪消息，找到目标 NI/Router，申请本 VNet 的空闲 VC，然后创建 flit 并等待发送机会。

```text
消息进入协议队列
 → NI 申请 VC
 → 消息拆为 flit，放入 NI 输出缓冲
 → 有 credit 和发送机会时逐个发送
```

“消息已经被 NI 接手”和“所有 flit 都已发出”是不同阶段。如果没有空闲 VC，NI 可能暂时不能接手消息；即使 flit 已生成，也可能因没有 credit 而留在 NI。

### 3.2 接收侧

NI 消费网络送来的 flit。非尾 flit 被消费后返回普通 credit；尾 flit 到达、协议接收队列可用且本周期交付条件允许时，NI 将其关联的消息交付协议队列。

若协议队列暂时满，NI 会保留尾 flit 并推迟交付及相应释放信号。目标端因此也能产生背压。收到消息之后，控制器仍需等队列就绪、执行状态转换，不能将包到达等同于 CPU 访存完成。

## 4. Router：逐跳选择方向并转发 flit

Router 的输入端口接收上游 flit，输出端口连接下游。Mesh 中可见 East、West、North、South 和本地端点方向，实际端口数量由拓扑决定。

```text
输入链路 → 输入端口/VC 缓冲 → 路由与仲裁 → Crossbar → 输出链路
```

Router 对包头计算输出方向，再检查下游资源，参与仲裁。获得机会后发送一个 flit；后续 flit 继续等待和竞争。方向已经确定并不代表立即能发。

等待可能来自：流水线尚未就绪、没有空闲下游 VC、没有 credit、消息顺序限制或仲裁失败。VC、credit 和背压分别解释其中的资源组织、容量约束和阻塞影响。

## 5. VC：虚拟通道到底是什么

### 5.1 它是一组独立缓冲与包状态

VC 全称 Virtual Channel，虚拟通道。Router 的每个输入端口可有多个 VC，每个 VC 保存等待的 flit，以及当前包的状态、输出方向和下游 VC 关联。

```text
Router B                        Router C
East 输出 ──一条物理链路──→ West 输入端口
                                ├─ VC0：[H][B]       包 P
                                ├─ VC1：[H][B][B]    包 Q
                                └─ VC2：[ ]          空闲
```

这些 VC 共享物理链路，发送机会需要仲裁；不是画三个 VC 就有三条物理链路。

### 5.2 为什么要多个 VC

假设输入中包 P 要向 East 发送，但 East 受阻；包 Q 要向可用的 North 发送。若 P、Q 在同一个 FIFO 且 P 位于队首，Q 也可能被挡住。

放在不同 VC 后，仲裁器可以独立检查 P 和 Q，Q 有机会继续向 North 前进。这可以缓解队头阻塞，但若它们都竞争同一个已满载输出，增加 VC 也不能直接增加该输出带宽。

### 5.3 空缓冲不等于空闲 VC

HEAD 已离开、BODY 还没到时，缓冲可能为空，但 VC 仍服务原包。不能把新包立即放进去。一个 VC 同时服务一个包，TAIL 离开后才能完成相应释放流程，再服务后一个包。

包可以跨多个 Router 分布，不必完整装进某个 VC。5-flit 包经过深度为 4 的 VC，是前面 flit 移出后给后续 flit 腾位置，并不要求一次装下 5 个。

### 5.4 本跳与下游 VC 编号可以不同

例如 B 的输入 VC2 中的包要去 C，B 为它申请到 C 的输入 VC5。包在 B 保存的关联为“输出 East，下游 VC5”；发送时携带下一跳所需 VC 编号。

VC2/VC5 是局部资源编号，不是包沿全程固定占有的编号，也不是为某个 CPU 永久专用的线路。

### 5.5 VNet 与 VC 的区别

VNet 按协议消息类别分组，VC 是每类内部使用的传输资源。例如教学 MSI 有请求、转发和响应三个 VNet，每类可以配置多个 VC。

```text
某输入端口，假设每 VNet 有 4 个 VC：
VNet 0 → VC0～VC3
VNet 1 → VC4～VC7
VNet 2 → VC8～VC11
```

各类有独立的 VC/缓冲组织，但仍可竞争同一个物理输出与链路。

## 6. Credit：告诉上游还能向哪个 VC 发多少

### 6.1 不是每个 Router 只有一个 credit

在 Router 到 Router 的基础连接中，上游按“输出端口下的每个下游 VC”分别维护额度。B 的 East OutputUnit 跟踪 C 的 West 输入 VC，而不是用一个数字代表整个 C：

| B 跟踪的下游资源 | 剩余 credit 示例 | 含义 |
|---|---:|---|
| C 的 West/VC0 | 4 | 还能预留 4 个 flit 槽位 |
| C 的 West/VC1 | 2 | 还能预留 2 个 flit 槽位 |
| C 的 West/VC2 | 0 | 当前不能继续向这个已分配 VC 发送 |

额度不能跨 VC 随意混用。是否可以让一个新包使用某个 VC，还需检查该 VC 是否空闲，不能只看 credit 是否为正。

### 6.2 发送时扣额度，反馈到达后加额度

假设 C 的某个输入 VC 深度为 4，初始向 B 提供 4 个额度，暂时没有 credit 返回：

| 事件 | B 保存的 credit |
|---|---:|
| 初始 | 4 |
| 发 F0 | 3 |
| 发 F1 | 2 |
| 发 F2 | 1 |
| 发 F3 | 0 |
| 想发 F4 | 必须等待 |

发送时就扣减，是为链路上尚未到达 C 的 flit 预留槽位。credit 不一定等于下游此刻物理空槽数，因为数据和反馈都可能在途。

C 从该输入 VC 移出 F0 后，产生对应 credit，经 CreditLink 返回；B 收到后才将额度加 1，并可再次发送。单纯等时间不会让额度自动恢复，必须有相应反馈。

### 6.3 普通 credit 与 free signal

| 反馈 | 下游表达的含义 | 上游更新 |
|---|---|---|
| 普通 credit | 释放一个缓冲槽，原包仍可能占用 VC | 额度增加，VC 仍可保持已分配 |
| 带 free signal 的 credit | 尾 flit 已移出，原包不再占用该 VC | 额度增加，并标记输出 VC 空闲 |

“有可用槽位”和“可将整个 VC 分给新包”是两个条件。发送包头需要获得空闲下游 VC；发出包尾也不等于立刻收到下游的释放反馈。

credit 是缓冲容量反馈，MSI 的 InvAck/PutAck 则是协议动作确认，不能互相替代。

## 7. 一个包怎样分配 VC 并逐跳传输

假设 P 从 B 的输入 VC2 到达，要经 East 输出前往 C：

1. HEAD 到达 B，B 将输入 VC2 标为 ACTIVE，计算 outport=East。
2. 等 flit 达到可仲裁时间，并满足消息顺序条件。
3. 包头需要 C 中属于同一 VNet 的空闲 VC。本地实现把输出 VC 分配合入交换分配，在仲裁获胜后建立关联。
4. 假设分到 C 的 VC5，B 将该下游资源标为已分配，发送 HEAD 并扣一个 credit。
5. BODY/TAIL 沿用 East/VC5，逐个检查 credit、竞争发送机会。
6. flit 离开 B 的输入 VC2 后，B 向自己的上游 A 返回 credit。
7. C 从输入 VC5 移出 flit 后，C 向 B 返回 credit。
8. TAIL 离开各跳输入 VC 时，分别触发各跳的 free signal；这些释放不是全网同时发生。

一个 Router 因此同时扮演接收方和发送方：它向前一跳反馈自己的缓冲空间，又跟踪后一跳给自己的额度。

## 8. 背压传播：下游停住，为什么上游也会停

### 8.1 场景与图示约定

只考虑一条经过 A→B→C 的流，每跳相关输入 VC 深度为 2；忽略未画出的其他流，假设下游阻塞持续足够久。下面的方框表示各 Router 中这条流所经过的输入 VC，不是整个 Router。

```text
源 NI → A 的输入 VC → B 的输入 VC → C 的输入 VC → 目标 NI
```

### 8.2 第一步：目标端处理不动

假设目标协议队列满，目标 NI 不能及时交付尾 flit，并暂缓相应释放反馈。随着后续包继续到来，C 向目标发送所需的资源逐渐耗尽，C 的相关输入缓冲开始积压。

```text
A：[ ][ ] → B：[ ][ ] → C：[F0][F1] → 目标侧受阻
```

目标 NI 在本地实现中仍可消费非尾 flit、保留无法交付的尾 flit，并不等于目标队列一满就停止消费所有 flit。因此这幅图表示持续阻塞后的可能状态，不是立即发生的同步变化。

### 8.3 第二步：B 也停下来

C 输入 VC 中的 flit 无法及时移出，就没有足够 credit 返回 B。B 仍可能继续使用剩余额度，但用完后不能再向 C 发送。这时 B 的相关输入 VC 逐渐积满：

```text
A：[ ][ ] → B：[F2][F3] ✕ C：[F0][F1]
```

B 暂时不能移出输入 flit，也就不能持续向 A 返还对应槽位额度。

### 8.4 第三步：A 和源端受到影响

A 的额度随后耗尽，无法向 B 发；A 的输入 VC 继续积压。最终源 NI 的发送与 VC 复用受阻，可能无法接手更多协议消息。

```text
源端受限 → A：[F4][F5] ✕ B：[F2][F3] ✕ C：[F0][F1]

数据方向：源 → A → B → C → 目标
阻塞影响：源 ← A ← B ← C ← 目标
```

这就是背压传播。Garnet 不一定另外发送一条叫“背压”的消息；credit/释放反馈迟迟不返回，上游资源耗尽后停止，就形成背压。

### 8.5 为什么不是所有 Router 同时停止

每跳都有自己的剩余槽位、在途 flit、在途 credit 和其他 VC。下游阻塞后，上游仍能继续发送一段时间，直到相应资源耗尽。

停止范围也有边界：其他 VC 或其他输出方向若有资源，仍可能工作；但它们也可能因共享仲裁、顺序限制或汇聚热点间接受影响。背压不是“整个 Router 一律关停”。

## 9. 下游恢复后怎样解除背压

恢复不是一个全网络广播，而是资源逐步释放：

```text
目标协议队列释放空间
 → 目标 NI 交付待交付消息，返还尾部释放反馈
 → C 获得发送/VC 复用机会，移出等待 flit
 → C 给 B 返回 credit
 → B 收到后发送，腾出自己的输入槽
 → B 给 A 返回 credit
 → A 和源端逐步恢复
```

多条流可能同时竞争刚释放的资源，因此恢复后仍可能等待仲裁。实际时序取决于链路、时钟、包长和队列状态，不能把恢复过程理解为每箭头固定一周期。

## 10. 背压、拥塞、死锁分别是什么

| 现象 | 含义 | 恢复条件 |
|---|---|---|
| 背压 | 下游资源不足，通过流控限制上游 | 相关资源释放并反馈，发送逐步恢复 |
| 拥塞 | 到达流量超过局部服务能力，等待持续积累 | 降低负载、增加瓶颈能力或改变流量分布 |
| 死锁 | 资源依赖形成无法自行解除的循环等待 | 需要从协议/路由/资源设计上避免或专门处理 |

例如 A 持资源 a 等 b，B 持 b 等 c，C 持 c 等 a，且不能释放已有资源时，可能形成死锁。正常背压没有必然的循环依赖，目标继续消费时可以解除。

多 VNet 有助于分离协议依赖，多 VC 可以增加独立资源和调度选择，但数量多不自动证明无死锁。还需分析路由转向、通道依赖、协议请求/响应关系和端点接收行为。

## 11. 源码对应关系

| 机制 | 入口 |
|---|---|
| NI 注入、flit 化、接收与尾部暂存 | [NetworkInterface.cc](../../../src/mem/ruby/network/garnet/NetworkInterface.cc)：wakeup、flitisizeMessage、checkStallQueue |
| Router 执行顺序 | [Router.cc](../../../src/mem/ruby/network/garnet/Router.cc)：wakeup |
| 输入缓冲、路由触发、返还上游 credit | [InputUnit.cc](../../../src/mem/ruby/network/garnet/InputUnit.cc) |
| VC 状态与缓冲 | [VirtualChannel.cc](../../../src/mem/ruby/network/garnet/VirtualChannel.cc) |
| 检查资源、仲裁、分配 VC、扣 credit | [SwitchAllocator.cc](../../../src/mem/ruby/network/garnet/SwitchAllocator.cc)：send_allowed、arbitrate_outports |
| 收 credit、增加额度、标记 VC 空闲 | [OutputUnit.cc](../../../src/mem/ruby/network/garnet/OutputUnit.cc)：wakeup |
| credit 字段与链路 | [Credit.hh](../../../src/mem/ruby/network/garnet/Credit.hh)、[CreditLink.hh](../../../src/mem/ruby/network/garnet/CreditLink.hh) |

## 12. 用五个问题检查是否理解

1. NI 已拆出 flit，为什么仍可能发不出去？——可能没有 credit 或未获得发送机会。
2. 一个 Router 有几个 credit？——按输出端口、下游 VC 分别维护计数，不是每 Router 一个数。
3. VC 缓冲空了能马上放新包吗？——不一定，原包后续 flit 可能还没到，需检查 VC 状态。
4. 下游释放槽位，上游能立刻发送吗？——需等对应 credit 到达并满足其他发送条件。
5. C 停止后为什么 A 还发了一会儿？——上游有剩余额度和缓冲，背压要在资源逐步耗尽后传播。

更详细的流水线、仲裁和统计口径见[核心知识点详解](garnet_core_concepts.md)，五个网络组件整体关系见[组件与 Packet/Flit 专题](garnet_components_and_flits.md)。
