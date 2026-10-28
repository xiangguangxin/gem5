# Part 5 · 第 3 章：Garnet 核心知识点详解

> 前置阅读：[Garnet 导读](garnet.md)、[MSI 的消息发送链路](msi_ruby_network.md)。
> 本文逐项讲解概念、工作过程、具体例子及性能影响，源码入口与掌握标准作为辅助。实现细节依据当前仓库 Garnet。实验部分是建议，尚未运行；以下时序示例均明确其假设，不代替仿真结果。

## 1. 学习重点总表

| 知识点 | 建议掌握程度 | 原因 |
|---|---|---|
| NetworkInterface | 理解原理 | 了解消息注入和接收 |
| Router | 深入理解 | NoC 性能建模的核心 |
| NetworkLink | 理解原理 | 分析带宽和传输延迟 |
| Packet / Flit | 深入理解 | 理解网络传输粒度 |
| Topology / Routing | 深入理解 | 影响跳数和路径竞争 |
| Virtual Network | 理解原理 | 理解协议消息的逻辑隔离 |
| Virtual Channel | 深入理解 | 理解资源共享和阻塞 |
| Credit Flow Control | 深入理解 | 理解背压和缓冲区管理 |
| Router Pipeline | 深入理解 | 理解延迟的来源 |
| Arbitration | 深入理解 | 理解竞争、公平性和吞吐量 |

“理解原理”要求能说明输入、输出、职责和关键等待条件，并定位源码。“深入理解”还要求能手推竞争与状态变化，解释性能因果关系，并设计控制变量实验。

## 2. NetworkInterface：消息与 flit 网络的接口

**掌握程度：理解原理。**

NI 的协议侧连接 MessageBuffer，网络侧连接 Router。发送时，从对应 VNet 的队列取消息，申请输出 VC，按消息大小拆成 flit，并安排发送；申请不到 VC 时可能无法接手消息。多目标消息在 NI 拆成多个单播包。

接收时，NI 处理到达的 flit，在尾 flit/单 flit 包到达且目标队列可接收时交付协议消息。若目标 MessageBuffer 满，NI 会保留待交付内容并处理背压，因此包到达网络出口不一定意味着控制器立即收到消息。

NI 还处理与相邻 Router 之间的 credit。它不决定 MSI 的 I/S/M 转换，协议转换由目标控制器完成。

源码：[NetworkInterface.cc](../../../src/mem/ruby/network/garnet/NetworkInterface.cc)。先读 wakeup、flitisizeMessage、calculateVC、checkStallQueue，再读统计入口 incrementStats。

**自检：**能画出 MessageBuffer → NI → Router 的发送路径，并区分“源端没有空闲 VC”和“目标协议队列满”这两种等待。

### 2.1 为什么控制器不直接连接 Router

MSI 控制器处理的是“地址 A 的 GetM”，Router 处理的是“某输入 VC 中的 flit 要去哪个输出”。前者关心协议含义，后者关心传输资源。NI 在两个层次之间转换表示，控制器因此不必知道每个 flit 在哪一跳。

NI 需要解决三个问题：消息属于哪个 VNet、目的控制器接在哪个 Router、消息需要多少个 flit。目标控制器编号与 Router 编号不是同一个概念，因为多个控制器可以通过各自 NI 连接同一个 Router。

### 2.2 一个 Data 消息的注入过程

假设 Data 建模大小为 72B，输出宽度为 16B，每包 5 flit：

1. NI 的 wakeup 发现 VNet 2 的发送 MessageBuffer 已就绪。
2. flitisizeMessage 读取 Destination，查找目标 NI 与 Router。
3. calculateVC 在 VNet 2 对应的 VC 范围内找空闲项，不能随意借用其他 VNet 的 VC。
4. 生成 5 个 flit，记录同一包标识、消息引用、目标与 VC，放入 NI 的输出缓冲。
5. 输出调度器根据 credit、顺序条件和端口机会逐个发送。创建了 5 个 flit，不等于同周期发出了 5 个。
6. 整条原始消息被接手后，才从协议发送队列移除。多播可分批接手已经获得 VC 的目标，剩余目标继续等待。

### 2.3 接收不是逐字节拼回一个软件数组

在当前仿真实现中，flit 保存消息引用及相关元数据，NI 用尾 flit 标识包传输完成，再将消息引用交付协议队列。它模拟的是按 flit 占用资源与经历延迟，不要求像真实电路那样重新从每个字节拼装一个对象。

非尾 flit 被消费后可返回普通 credit；尾 flit 如果遇到协议接收队列满，会进入 NI 的 stall queue，等交付成功后才返回带 free signal 的 credit。这会推迟相邻 Router 复用该 VC，即使链路本身没有故障也会产生背压。

## 3. Router：路由、缓冲、分配与交换

**掌握程度：深入理解。**

Router 接收上游 flit，在输入 VC 中保存它，选择输出方向，参与输出资源竞争，获胜后经交叉开关送往下游。它还根据下游 credit 判断是否可以继续发送。

```text
上游 Link → InputUnit / 输入 VC → SwitchAllocator → CrossbarSwitch → 下游 Link
                         ↑             ↑
                    RoutingUnit    OutputUnit 保存下游 VC/credit 状态
```

| 模块 | 主要职责 |
|---|---|
| InputUnit | 接收 flit、维护输入 VC、包头路由计算、返回 credit |
| RoutingUnit | 为包头计算输出端口 |
| SwitchAllocator | 检查资源和顺序条件，仲裁输入/输出，分配输出 VC |
| CrossbarSwitch | 将获胜 flit 从输入送往对应输出 |
| OutputUnit | 维护输出 VC 状态，接收 credit 并更新额度 |

Router::wakeup 依次调用输入单元、输出单元、交换分配器和交叉开关。阅读时要区分“本周期被唤醒”“flit 已达到可仲裁时间”和“实际赢得发送机会”。

源码：[Router.cc](../../../src/mem/ruby/network/garnet/Router.cc)、[InputUnit.cc](../../../src/mem/ruby/network/garnet/InputUnit.cc)、[OutputUnit.cc](../../../src/mem/ruby/network/garnet/OutputUnit.cc)。

**自检：**给定两个输入都请求 East 输出，能说明包头还需要什么资源、谁参与仲裁、失败者保留在哪里。

### 3.1 输入端口、输出端口和 VC 分别在哪里

二维 Mesh 内部 Router 常见 North、South、East、West 和 Local 等方向，但实际端口数量由拓扑决定。Local 表示通向端点的连接，不代表某一个固定 CPU；一个 Router 可以连接多个本地端点。

一个输入端口下面有多个 VC，VC 保存 flit 和包状态。输出端口则有指向下游的链路，以及用于追踪下游 VC 的 OutputUnit。输入侧存放实际等待的 flit，输出侧维护“我能否往下游发”的状态，二者不能混为同一组队列。

### 3.2 包头在 Router 中经历什么

假设包 P 从 West 输入，要往 East 输出：

```text
West 输入 VC3：P 的 HEAD 到达
 → 将 VC3 从 IDLE 标为 ACTIVE
 → RC 算出 outport=East，记录在输入 VC3 中
 → 等待该 flit 达到 SA 就绪时间
 → 检查 East 是否有属于该 VNet 的空闲下游 VC
 → SA 获胜，分配 outvc=VC5
 → 从 VC3 取出 HEAD，扣减 East/VC5 的 credit
 → HEAD 穿过 Crossbar，向下游发送时携带 VC5
```

后续 BODY/TAIL 在当前输入 VC3 中沿用 outport=East、outvc=VC5，不为每个 BODY 重新查路由。VC5 对下一跳来说就是输入 VC 编号；当前跳的 VC3 不会作为全程身份保留。

### 3.3 Router 为什么会成为瓶颈

不同输入要去不同输出时，Crossbar 可以支持多个不冲突的传输；都要去 East 时，即使其他输出空闲，也受 East 的单端口发送能力限制。扩大缓冲可以让更多 flit 等待，却不能凭空增加 East 的物理带宽。

所以分析瓶颈应先问“都在竞争同一个输出吗”，再问“是不是没有下游 VC/credit”，最后看仲裁与流水线。三类原因可能同时存在，但对应的优化手段不同。

## 4. NetworkLink：区分传输延迟与带宽

**掌握程度：理解原理。**

NetworkLink 将源队列中的 flit 按链路延迟交给消费者。延迟描述一个 flit 经过链路需要多久；带宽描述单位时间可以持续传送多少数据，两者不是同一个量。

在同频、同宽、无阻塞的基础链路模型中，一条有流水能力的链路可连续逐周期发送 flit；将链路延迟设为多个周期，不等于只能每隔多个周期发一个 flit。实际实现阅读 NetworkLink::wakeup 的发送和再次唤醒逻辑。

例如，假设每周期可发送 1 个 16B flit、频率 1GHz，则单方向原始带宽为 16GB/s。协议开销、空闲周期和竞争会降低有效负载吞吐量。跨时钟域或变宽时，还需分析 NetworkBridge，不能直接沿用同频公式。

源码：[NetworkLink.cc](../../../src/mem/ruby/network/garnet/NetworkLink.cc)、[GarnetLink.py](../../../src/mem/ruby/network/garnet/GarnetLink.py)、[NetworkBridge.cc](../../../src/mem/ruby/network/garnet/NetworkBridge.cc)。

**自检：**能分别解释增加 link latency、增加 link width 对首 flit 到达时间、包序列化时间和持续吞吐量的影响。

### 4.1 多周期延迟的链路也可以流水传输

下面只观察链路：同频、每周期接收一个 flit、latency=3、持续有数据且下游已预留空间。周期编号表示链路接收或交付时刻：

| 周期 | 链路接收 | 链路交付 |
|---|---|---|
| 0 | F0 | — |
| 1 | F1 | — |
| 2 | F2 | — |
| 3 | F3 | F0 |
| 4 | F4 | F1 |
| 5 | — | F2 |
| 6 | — | F3 |
| 7 | — | F4 |

首 flit 等 3 周期，但稳定阶段每周期仍交付 1 flit。若链路改成“每 3 周期才能接收一个”，则带宽也降低了；这不是单改 link latency 所表达的模型。

### 4.2 加宽链路为什么主要帮助长包

假设控制消息 8B，数据消息 72B，比较统一网络宽度：

| 每 flit 字节数 | 控制消息 flit 数 | 数据消息 flit 数 |
|---|---|---|
| 8B | 1 | 9 |
| 16B | 1 | 5 |
| 32B | 1 | 3 |

加宽后，数据包占据输出机会的次数减少，尾 flit 更早有机会发完，竞争压力也可能下降。控制消息已经是单 flit 时，不能再把包缩成半个周期；其固定 Router/Link 延迟仍存在。

只看位宽不能确定整条路径性能，还需要频率、两端吞吐能力、credit 往返和最窄瓶颈。修改宽度时要确保 Router、Link 和 NI 的配置一致，异构边界由桥接机制处理。

### 4.3 数据链路和 credit 链路为什么分开

flit 沿数据方向从上游到下游，credit 沿相反方向返回，告诉发送方下游释放了多少空间。双向拓扑连接通常还包含反方向独立的数据传输，不能将“返还 credit”理解成反向发送一个 MSI Data 包。

延长数据链路会让 flit 更晚占用和离开下游缓冲；延长 credit 链路会让上游更晚知道缓冲已经释放。两者都可能延长流控反馈回路，即使数据链路有逐周期发送能力，也可能因为额度不足无法满载。

调试时先看数据是否成功进入链路、何时到达消费者，再看相应 credit 是否产生、何时返回。这样可以区分传输延迟、下游不消费和反馈尚未到达三种原因。

## 5. Packet / Flit：包的边界与传输粒度

**掌握程度：深入理解。**

协议消息具有地址、消息类型、目标和数据等字段。NI 按目标形成网络包，并将包拆成 flit。包头 HEAD 携带路由所需信息，BODY 为中间部分，TAIL 标记包结束；单 flit 包类型是 HEAD_TAIL。

```text
多 flit 包：HEAD → BODY → BODY → BODY → TAIL
单 flit 包：HEAD_TAIL
```

同一包在一个输入 VC 中沿用包头选定的输出方向和为该包分配的输出 VC。尾 flit 离开该输入 VC 后，才能通过 free signal 通知上游相应 VC 可以被另一个包使用。

flit 数按消息字节数除以实际输出宽度并向上取整。例如 64B 数据加 8B 控制开销，在 16B/flit 下为 ceil(72/16)=5 flit。不要把任何 Data 消息都无条件记为 5 flit。

包长为 5 flit、VC 深度为 4 flit 仍然可以运行：前面的 flit 离开并释放槽位，后面的 flit 继续进入；无需让整个包同时驻留一个缓冲区。

源码：[flit.hh](../../../src/mem/ruby/network/garnet/flit.hh)、[CommonTypes.hh](../../../src/mem/ruby/network/garnet/CommonTypes.hh)、NetworkInterface::flitisizeMessage。

**自检：**能分别计算消息数、单播包数和 flit 数，并说明多播和宽度变化会怎样影响这些数量。

### 5.1 为什么要将包拆成 flit

物理链路一次只能传一定宽度的数据。把不同长度的消息都拆成统一流控单位后，路由器可以按 flit 分配缓冲与交换机会，长包也可以在尚未全部到达时继续向前推进。

假设 P 为 H、B1、B2、B3、T。H 已在 R2 时，B2 可能还在 R1，T 仍在源 NI。同一个包因此跨多个节点占用 VC，并可能因前方阻塞将等待向后传播。这是理解 wormhole 类传输行为的关键。

### 5.2 Packet 级资源与 flit 级资源

| 资源/动作 | 通常按什么粒度处理 |
|---|---|
| 当前输入 VC 的包身份、输出方向与下游 VC 关联 | 包 |
| 链路发送、Crossbar 竞争、缓冲槽与 credit | flit |
| 下游 VC 的重新分配 | 需等待前一包释放 |

一个包占有下游 VC，并不表示它独占整个物理链路直到尾部通过。其他 VC 的 flit 可以在满足条件时穿插使用同一个链路；同一包内部的先后关系仍须保持。

### 5.3 用 MSI 的失效消息计算流量

假设一个 Inv 消息的 Destination 包含 3 个 Sharer，控制消息大小为 8B，flit 为 16B。若三个目标各生成一个单播，则是 1 条原始多目标消息、3 个包、总共 3 个 flit。各 Sharer 返回 InvAck 又产生额外网络流量。

因此“本次协议动作只发了一条消息”和“网络只传了一次”不是一回事。统计性能时要同时观察包数、flit 数及每个包走过的链路，才能解释网络负载。

## 6. Topology / Routing：连接关系与路径选择

**掌握程度：深入理解。**

Topology 定义 Router、端点与链路如何连接；Routing 在现有连接中选择输出方向。同一个 Mesh 可以使用不同路由策略；选择 Mesh 拓扑并不自动将 routing_algorithm 改成 XY。

| 机制 | 当前实现含义 |
|---|---|
| 算法 0：查表 | 匹配目标，在候选输出中选择最小权重；等权选择还取决于 VNet 是否 ordered |
| 算法 1：XY | 按坐标先完成 X 方向，再完成 Y 方向 |
| 算法 2：Custom | 自定义入口，需要实现相应函数 |

无障碍二维 Mesh 中，最短内部路由器链路数为 abs(x1−x0)+abs(y1−y0)。这一计算不包含端点到 Router 的外部链路，也不等于完整端到端周期数。

链路权重影响路径选择，链路延迟影响经过该链路的时间。最少跳数路径不一定在有竞争时延迟最低；自适应选择还必须考虑消息顺序、死锁和饥饿。

源码：[Mesh_XY.py](../../../configs/topologies/Mesh_XY.py)、[Topology.cc](../../../src/mem/ruby/network/Topology.cc)、[RoutingUnit.cc](../../../src/mem/ruby/network/garnet/RoutingUnit.cc)。

**自检：**能在 4×4 Mesh 上手画几对端点的 XY 路径，指出共享哪些链路、哪里可能形成热点。

### 6.1 拓扑先决定哪些路径存在

假设 4×4 Mesh 中 Router 编号按 row-major 排列，坐标写成 (x,y)：

```text
(0,3) ─ (1,3) ─ (2,3) ─ (3,3)
  │       │       │       │
(0,2) ─ (1,2) ─ (2,2) ─ (3,2)
  │       │       │       │
(0,1) ─ (1,1) ─ (2,1) ─ (3,1)
  │       │       │       │
(0,0) ─ (1,0) ─ (2,0) ─ (3,0)
```

从 (0,0) 到 (3,2) 的 XY 路径先沿 X 到 (3,0)，再沿 Y 到 (3,2)，共 5 条内部链路。若采用 YX，跳数仍为 5，经过的链路却不同；两种流量的竞争位置因此可能改变。

### 6.2 为什么最短路径仍然可能很慢

若很多源同时向右上角目标发送，靠近该目标的链路和端点出口会形成汇聚瓶颈。即便所有包都走最短路径，最后一跳仍不能同时服务所有包。增加上游 VC 可能只使队列更长，无法突破目标出口容量。

替代路径可在有冗余时分散部分链路竞争，但不能消除所有汇聚瓶颈。比较拓扑也要控制资源：更多链路、更宽横截面或更多 Router 往往意味着不同成本。

### 6.3 路由与死锁的联系

假设包 A 占着通道 a 等 b，B 占 b 等 c，C 占 c 等 a，且无法释放已有资源，就可能构成循环等待。固定维度顺序使允许的转向受限，有助于在规则 Mesh 中消除特定路由通道依赖环。

这不等于 XY 自动证明整个系统无死锁：协议队列、VNet 分配、NI 和目标接收行为仍需纳入分析。自定义自适应路由也不能只看“哪边 credit 多就走哪边”，还要给出依赖约束或逃逸机制等设计依据。

## 7. Virtual Network：协议流量的逻辑隔离

**掌握程度：理解原理。**

VNet 区分协议消息类别。教学 MSI 的 VNet 0 为请求，1 为转发/失效/PutAck，2 为 Data/InvAck。消息队列的 SLICC 声明决定所属 VNet。

分离请求和响应有助于避免响应被阻塞请求占据的资源卡住，但多个 VNet 本身不是无死锁证明；仍需分析协议依赖、路由通道依赖和有限缓冲。

VNet 不等于一套独占的物理链路。不同 VNet 的 flit 仍可能竞争同一个输出端口和链路；逻辑隔离不保证带宽隔离或固定优先级。

源码：[MSI-cache.sm](../../../src/learning_gem5/part3/MSI-cache.sm)、[MSI-dir.sm](../../../src/learning_gem5/part3/MSI-dir.sm) 中的 MessageBuffer 声明，以及 [Network.cc](../../../src/mem/ruby/network/Network.cc) 中的队列注册。

**自检：**能解释 VNet 由谁定义、为什么分组，以及为什么 VNet 分开后仍有网络竞争。

### 7.1 为什么协议需要区分请求与响应

设想某类请求占满所有可用缓冲，而这些请求又必须等待响应才能完成。如果响应还需要挤入同一组已经占满的缓冲，响应不能前进，请求也无法释放资源，就可能形成协议层资源依赖。

将请求与响应划入不同 VNet，可以为后者提供独立的 VC/缓冲类别，使它不必等待请求占用的同一类槽位。这是分离消息类别的目的；真正是否安全仍要检查整个依赖图。

### 7.2 VNet 怎样落实到 VC

假设 VNet 数为 3，每个 VNet 有 4 个 VC，则某输入端口上的 VC 编号可理解为：

```text
VNet 0：VC 0、1、2、3
VNet 1：VC 4、5、6、7
VNet 2：VC 8、9、10、11
```

本地可以用 vc / vcs_per_vnet 得到所属 VNet。消息从指定 VNet 注入后，VC 选择也在这一组内进行；不是每经过一个 Router 就可随意改成其他协议类别。

### 7.3 为什么逻辑隔离后仍会互相拖慢

假设 GetM 和 Data 分别属于 VNet 0 与 2，它们虽使用不同 VC，但若都要从 Router 的 East 端口离开，仍需要竞争同一个 Crossbar 输出和链路周期。响应有自己的缓冲，不代表每周期都先于请求获胜。

ordered VNet 还给同类消息增加顺序限制。VNet 的编号、ordered 属性和仲裁优先策略是不同维度；不能仅由编号大就推断当前 Garnet 中始终严格优先发送。

## 8. Virtual Channel：共享物理链路的独立包状态

**掌握程度：深入理解。**

每个输入端口按 VNet 配置多个 VC；每个 VC 有自己的缓冲和包状态。多个 VC 共享同一个物理输入/输出传输机会，但可以独立等待下游资源。

典型例子：输入 VC0 的包等待 East 下游 credit，输入 VC1 中另一个包要去 North。若 VC1 满足发送条件，仲裁器可以选择它，减少其他包被阻塞包拖住的机会。这是缓解队头阻塞的方式，不保证总能消除阻塞。

一个 VC 同时服务一个包，不表示整个包都在 VC 缓冲里。输入 VC 编号是本跳资源，下游可能分配不同编号；包没有沿整条路径预留一个全局固定 VC。

若每端口有 V 个 VNet，每个 VNet 有 C 个 VC，则每输入端口的 VC 数为 V×C。若其中 Vd 个是数据类、Vc 个是控制类，深度分别为 Bd/Bc，则该输入端口的名义缓冲槽数为 C×(Vd×Bd+Vc×Bc)。这只计算输入 VC 槽位，不含 NI 等其他缓冲。

增加 VC 在固定每 VC 深度时通常增加总缓冲和状态资源，不保证带宽或性能按比例提高。

源码：[VirtualChannel.cc](../../../src/mem/ruby/network/garnet/VirtualChannel.cc)、[OutVcState.cc](../../../src/mem/ruby/network/garnet/OutVcState.cc)、[GarnetNetwork.py](../../../src/mem/ruby/network/garnet/GarnetNetwork.py)。

**自检：**能区分空闲 VC、已分配但仍有空槽的 VC，以及有待发 flit 却无法前进的 VC。

### 8.1 单 FIFO 为什么容易出现队头阻塞

假设一个输入只有一条 FIFO，队列中包 A 在前、包 B 在后：A 要去 East，但 East 下游没有空间；B 要去空闲的 North。B 不能越过 FIFO 队首的 A，于是一个方向的阻塞拖住另一个本可前进的方向。

若 A、B 被放入不同 VC，仲裁器可以分别检查它们。A 的 VC 不可发送时，B 的 VC 仍有机会去 North。这增加了调度选择，而不是增加了一条新的物理链路。

### 8.2 已分配、空缓冲与空闲 VC

假设包 A 的 HEAD 已离开当前输入 VC，而 BODY 还未到达。此时 VC 缓冲可能为空，但该 VC 仍属于 A，必须保存 A 的状态，不能因为 FIFO 空了就放进包 B。

只有 A 的 TAIL 离开并完成释放逻辑后，VC 才能用于下一个包。上游也要等 free signal 返回才能知道这一点。所以读代码时必须分别检查 buffer 是否有 flit 和 VC 状态是否 IDLE。

### 8.3 增加 VC 的收益边界

如果瓶颈是一个被阻塞包挡住其他目的包，增加 VC 可能帮助较大；如果所有 VC 都去同一条已满载链路，更多 VC 主要增加等待容量。如果 ordered VNet 不允许后来的同方向包越过早到包，也不能靠多 VC 任意绕过顺序约束。

在默认 3 个 VNet、每 VNet 4 个 VC，并假设 2 类控制 VNet 深度 1、1 类数据 VNet 深度 4 时，每输入端口名义槽数是 4×(2×1+1×4)=24。每 VNet 改成 8 个 VC 而保持深度，就变成 48 个槽；性能收益需要连同资源增长一起解释。

## 9. Credit Flow Control：下游空槽与背压

**掌握程度：深入理解。**

上游维护下游 VC 的可用缓冲额度；发送一个 flit 消耗一个 credit，下游移出一个 flit 后返还一个 credit。credit 到达前，上游不能提前当作该空槽已经可用。

假设缓冲深度为 4、初始额度为 4，在尚未收到返回 credit 时连续发出 4 个 flit，额度变为 0。第 5 个 flit 必须等待，即使下游实际上刚释放槽位，也要等反馈到达后才能使用额度。这解释了 credit 往返时间与缓冲深度如何影响链路利用率。

| 反馈 | 表示什么 |
|---|---|
| 普通 credit | 释放一个缓冲槽，原包仍可能占用该 VC |
| 带 free signal 的 credit | 尾 flit 已离开，VC 可以重新分配给其他包 |
| MSI InvAck | 协议中的副本失效确认，与缓冲空间无关 |

本实现中，包头若尚无输出 VC，send_allowed 检查是否有空闲 VC；空闲 VC 的初始化额度保证可以发送首 flit。已有输出 VC 的后续 flit 则检查 credit。获胜发送时，对应额度统一扣减。

背压可以逐跳传播：目标队列无法接收 → NI 交付受阻 → 下游 VC 不能及时释放 → credit 不足 → 上游停止前进。它不是丢包或立即触发协议重试的同义词。

源码：[Credit.hh](../../../src/mem/ruby/network/garnet/Credit.hh)、[CreditLink.hh](../../../src/mem/ruby/network/garnet/CreditLink.hh)、InputUnit::increment_credit、OutputUnit::wakeup、SwitchAllocator::send_allowed。

**自检：**能手推一个短包的 credit 数变化，并说明槽位释放与 VC 释放的区别。

### 9.1 credit 是保守的可用额度

credit 计数不一定等于下游此刻物理空槽数，因为 flit 和 credit 都可能在途。发送后立即扣额度，是为在途 flit 预留位置；等返回 credit 到达才加额度，是避免重复使用同一个槽。

在无重复或丢失的基础模型下，对一个已分配、容量为 B 的下游 VC，可用下面的账本理解资源守恒：

```text
B = 上游尚可使用的 credit
  + 已预留位置的在途 flit
  + 下游尚未移出的 flit
  + 空槽已释放但 credit 仍在返程的数量
```

它解释了为什么“下游看起来空了，上游仍然不能立刻发”不一定是错误。

### 9.2 一张具体的额度变化表

假设 B=2，表格只列事件顺序，省略固定链路周期：

| 事件 | 上游 credit | 解释 |
|---|---|---|
| 初始 | 2 | 两个槽均可预留 |
| 发 H | 1 | 为包头预留一个槽 |
| 发 B1 | 0 | 两个槽已被占用或预留 |
| 下游移出 H | 0 | credit 正在返回，上游尚不知道 |
| 收到 H 的普通 credit | 1 | 可以发下一 flit，但 VC 仍归原包 |
| 发 T | 0 | 尾 flit 也消耗一个槽位额度 |
| 下游最终移出 T | 依返回事件而定 | 生成带 free signal 的 credit |
| 上游收到该 free signal | 随返回 credit 增加 | 对应输出 VC 才可重新分配 |

B1 的 credit 也会独立返回，未在表中逐项展开。额度按所有发送和返回事件累计，不能把“收到尾部 free signal”理解成忽略此前槽位账本。

### 9.3 缓冲深度为什么与往返延迟有关

若一个 VC 想持续每周期发 1 flit，而从扣除某槽额度到额度返回要经历 R 个周期，就需要足够多额度覆盖这段反馈空窗。深度太小时，额度会先耗尽，链路出现气泡。

这是理解带宽时延积的直觉，不是给任意 Garnet 配置都适用的精确 B=R 定律；Router 处理、仲裁、其他 VC 和端点阻塞会改变实际回路。增加深度也不能让一个长期不消费数据的目标无限吸收流量。

## 10. Router Pipeline：固定处理时间与动态等待

**掌握程度：深入理解。**

阅读顺序为输入缓冲 BW、包头路由计算 RC、交换仲裁 SA、输出 VC 选择、交换穿越 ST、链路穿越 LT。概念阶段数不等于每个阶段固定占一个独立周期。

本地实现把 VC 分配合入交换分配。router latency=1 时，输入就绪 flit 可在同周期参与 SA/ST；多周期路由器通过在输入缓冲中等待 latency−1 周期后才允许参与 SA 来建模。LT 继续使用链路延迟。

每个包还会经历注入等待、争用、credit 等待、序列化以及目标交付等待。因此增加 router latency 是改变固定处理条件，拥塞额外等待则随负载和资源状态变化。

用于分析的分解可以写为：

```text
端到端时间
 = 源端等待 + 网络内部传输与等待 + 目标交付等待

网络内部部分受以下因素影响：
路由器处理、链路延迟、包长与序列化、仲裁、VC 与 credit 等待
```

这不是可直接逐项累加所有流水阶段的精确公式；不同 flit/不同跳之间可以重叠。推算前要声明观察的是包头还是尾 flit、是否有争用，以及是否包含 NI。

源码：InputUnit::wakeup、[SwitchAllocator.cc](../../../src/mem/ruby/network/garnet/SwitchAllocator.cc)、[CrossbarSwitch.cc](../../../src/mem/ruby/network/garnet/CrossbarSwitch.cc)、NetworkLink::wakeup。

**自检：**能画出单 flit 的低负载时间线，再加入竞争请求，标出哪些延迟是固定的、哪些是动态等待。

### 10.1 先分清“逻辑阶段”与“每周期发生的事”

BW、RC、SA、ST 是功能划分。Garnet 的默认配置可以在一次 Router 唤醒中推进多个功能步骤：输入单元先处理新到 flit，分配器再处理已就绪候选，Crossbar 随后处理赢家。因此不能看到四个名字就直接计为四周期。

多周期配置则主要改变 flit 何时可以参与 SA。被唤醒的 Router 可以同时服务多个处在不同状态的 flit；它不是先把整个包处理完，再接下一包。

### 10.2 在同一个 Router 上手推两个包

以下周期从输入 flit 被当前 Router 消费开始，只看该 Router 的处理，不包含此前链路和 NI。假设 router latency=2、HEAD_TAIL 已到达、可立即分配下游 VC且无顺序限制：

| 周期 | 包 A | 包 B（下一周期到达） |
|---|---|---|
| 0 | BW/RC，设为周期 1 才可参与 SA | 尚未到达 |
| 1 | 若仲裁获胜，SA/ST，安排后续输出 | BW/RC，设为周期 2 可参与 SA |
| 2 | 已进入后续链路过程 | 若仲裁获胜，SA/ST |

每包都有进入 SA 前的等待，但连续包的处理可以重叠。链路真正开始消费与到达下游的时间，还需加入 Crossbar/NetworkLink 的事件安排，表格不直接给出端到端延迟。

### 10.3 为什么负载升高后延迟突然上升

低负载下，多数 flit 一旦就绪即可获胜，主要体现固定处理和传输时间。接近某条链路的服务能力时，多个包不断积累，等待多个仲裁周期；积累的队列又耗尽下游 credit，背压进一步扩散。

因此饱和附近的延迟增长主要来自排队，不能都归因于 router latency。诊断时应同时看实际接收吞吐量和等待情况；只把流水级改少，未必能解决热点链路容量不足。

## 11. Arbitration：谁能使用共享资源

**掌握程度：深入理解。**

Routing 先决定想去哪个输出；Arbitration 决定本周期谁可以使用它。找到了路径，不代表已经获得传输机会。

当前 SwitchAllocator 使用两级可分离仲裁：

1. SA-I：每个输入端口扫描自己的 VC，从可发送候选中选一个，向其目标输出提出请求。
2. SA-II：每个输出端口从请求它的输入中选择一个赢家；必要时分配输出 VC，取出 flit 并安排交换穿越。

若两个输入同时请求 East，每周期该输出最多选择一个赢家。若一个输入下有多个可发送 VC，SA-I 先筛选意味着其余 VC 本周期不会继续参与 SA-II；这种分级结构可能错过其他可并行发送的匹配。

实现使用轮询指针推进选择，同时在 send_allowed 中加入 ordered VNet 的包顺序检查。顺序限制可能让某个资源条件满足的包仍暂时不能发送。

公平性要区分竞争者获得机会是否均衡、是否存在长时间等待，以及不同包长/流量模式下吞吐量是否均衡。不能仅凭“round-robin”就推导每个端点端到端延迟相同；多跳竞争和背压仍会产生差异。

源码：SwitchAllocator::arbitrate_inports、arbitrate_outports、send_allowed、vc_allocate。

**自检：**能手推多个周期的请求、赢家和轮询指针变化，并比较单输出竞争与多个不冲突输出的情况。

### 11.1 一个两输入、两输出的具体例子

假设所有候选均满足 credit 与顺序条件：

```text
输入 I0：VC0 的 A → East；VC1 的 B → North
输入 I1：VC0 的 C → East
```

如果 SA-I 在 I0 选 A、在 I1 选 C，那么 SA-II 的 East 只能选一个赢家，North 没有请求而空闲。虽然 B 本来可以使用 North，但 I0 本周期已经只提交了 A。这说明可分离仲裁不保证每周期得到全局最大匹配。

若下一轮 I0 选 B，I1 选 C，则 North/East 可分别选中它们，形成两个并行传输。增加输入 VC 提供更多候选，但 SA-I 的选择仍影响资源利用率。

### 11.2 Round-robin 怎样推进

假设 East 有两个持续可发送的输入 I0/I1，只有一个相关候选 VC、无额外顺序与资源阻塞，初始指针从 I0 开始：

| 仲裁轮次 | 从哪个输入开始查找 | 赢家 | 下一起点 |
|---|---|---|---|
| 0 | I0 | I0 | I1 |
| 1 | I1 | I1 | I0 |
| 2 | I0 | I0 | I1 |

本地在真正赢得交换机会后更新相应输出端口的输入轮询指针，以及获胜输入的 VC 轮询指针。仅有请求或扫描到一个 VC，不等于它已经获得服务。

若 I0 因无 credit 不可发送，I1 可以继续获胜；所以观察到不严格交替不能直接认定仲裁失去公平性，要先看候选是否具备资格。

### 11.3 Flit 公平、包公平与端点公平

假设两个流每轮各得到一个 flit 机会，A 每包 1 flit、B 每包 5 flit。两者 flit 带宽可能接近，但 A 完成的包数可明显更多。再加上 A、B 的跳数和上游阻塞不同，端到端完成时间也不会相等。

ordered VNet 的检查还会阻止同一输入、同 VNet 中较晚到且请求同一输出的候选越过更早就绪包。它是局部的顺序约束，不应描述成全网络所有消息的全局 FIFO。

分析公平性时应说明比较对象和单位：每输入、每 VC、每源端点，或按 flit/包计数；平均吞吐量之外，还可记录最长等待或延迟分布，判断是否存在某个流长期得不到服务。

## 12. 用一条 GetM 把知识点串起来

```text
MSI sendGetM → MessageBuffer（VNet 0）
 → NI 选择 VC，构造包和 flit
 → 按拓扑进入 Router
 → 包头查路由，确定输出
 → 等待流水线就绪、空闲输出 VC 或 credit
 → 仲裁获胜，经过 Crossbar 和 NetworkLink
 → 逐跳重复
 → 目标 NI 向 Directory 的 MessageBuffer 交付
 → Directory 执行协议转换，产生 Inv/Data 等后续消息
```

NI 负责端点接入；Packet/Flit 决定传输粒度；Topology/Routing 决定路径；VNet/VC 组织消息和资源；credit 约束下游容量；pipeline、仲裁和链路共同决定时序与吞吐量。

## 13. 建议完成的四个练习

| 练习 | 操作 | 验收 |
|---|---|---|
| 概念手推 | 一个 5-flit 包经过深度为 4 的 VC | 写清 credit 返回、尾 flit 与 VC 释放 |
| 路径追踪 | 在固定 Mesh 中追踪单源单目标低负载包 | 对应 NI、输入 VC、输出方向、链路和目标队列 |
| 竞争观察 | 两个源持续请求同一方向或热点目标 | 区分路径竞争、credit 等待与仲裁等待 |
| 参数比较 | 固定其余参数，分别改变 VC、宽度或 router latency | 解释低负载延迟与接收吞吐量变化，注明资源预算 |

实验前核对构建协议与网络配置。合成流量使用 Garnet_standalone；教学 MSI 默认仍是 SimpleNetwork。记录预热、测量区间、随机种子、注入/接收数量、统计单位和未完成流量，避免把建议当作已验证结果。
