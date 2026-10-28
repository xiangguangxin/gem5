# Part 5 · 第 4 章：Garnet 五个核心组件与 Packet/Flit 的完整旅程

> 前置阅读：[MSI 消息发送链路](msi_ruby_network.md)、[核心知识点详解](garnet_core_concepts.md)。
> 本文依据当前仓库源码解释基础同频、同宽网络，异构宽度与时钟桥接仅列作扩展。图表是原理示意，本次未运行仿真。

## 1. 五个组件分别解决什么问题

Garnet 将 Ruby 控制器产生的协议消息转换成网络传输，并模拟传输中的资源竞争和延迟。先把五个组件放到同一张图里：

```text
                  GarnetNetwork：初始化连接、端点映射、网络级参数和统计

协议发送队列 → 源 NetworkInterface → NetworkLink → Router
                                                    │
                                               NetworkLink
                                                    ↓
协议接收队列 ← 目标 NetworkInterface ← NetworkLink ← Router

每段 flit 传输都有配套的反向 credit 反馈：
上游发送方 ─────── NetworkLink：flit ───────→ 下游接收方
上游发送方 ←────── CreditLink：credit ────── 下游接收方
```

GarnetNetwork 是组织这些对象的网络级组件，不是每个包必须经过的中心交换节点。数据沿拓扑中的 NI、Router 和 Link 前进。

| 组件 | 输入与输出 | 核心问题 |
|---|---|---|
| NetworkInterface，简称 NI | 协议 MessageBuffer ↔ 网络 flit | 如何注入、拆包、接收和交付协议消息？ |
| Router | 输入链路 flit → 输出链路 flit | 向哪走、能否走、本周期谁先走？ |
| NetworkLink | 源端待发 flit → 下游消费者 | 一次传输要等多久，能多快连续发送？ |
| CreditLink | 下游释放空间的反馈 → 上游额度状态 | 上游还可以往下游发送多少 flit？ |
| GarnetNetwork | 配置、拓扑连接、端点队列和统计 | 所有局部组件怎样组成完整网络？ |

## 2. NetworkInterface：从协议消息进入网络

### 2.1 为什么需要 NI

MSI 控制器理解 GetM、Data、InvAck 等协议消息，但不直接分配每一跳的链路周期。Router 理解端口、VC、flit 和 credit，也不执行 MSI 状态转换。NI 在两种表示之间建立连接。

NI 的协议侧连接发送/接收 MessageBuffer；网络侧连接 Router。一个 Router 可以通过不同 NI 连接多个控制器，所以控制器、NI 和 Router 不应都当成同一个编号。

### 2.2 发送侧逐步做什么

以一个单目标 Data 为例：

1. wakeup 检查各 VNet 的协议发送队列，发现就绪消息。
2. flitisizeMessage 读取目标集合和消息大小，找到该 VNet 使用的输出端口。
3. calculateVC 在该 VNet 的范围内寻找空闲输出 VC。
4. 将目标控制器映射到目标 NI 与 Router，生成路由信息。
5. 按消息大小和输出宽度计算 flit 数，创建包标识和各个 flit。
6. 将 flit 放入 NI 输出 VC 缓冲，记录包已占用此 VC。
7. 输出调度检查 credit 等条件，将 flit 逐个送到链路。

申请不到 VC 时，消息不能完成接手；创建出 flit 也不代表它们已经离开 NI。协议队列、NI 输出缓冲和链路缓冲是不同的等待位置。

多目标消息会按目标分别产生单播包。如果只完成了一部分目标的 flit 化，原消息中剩余目标可以留待后续处理，而不是重新给已完成目标重复发包。

### 2.3 接收侧逐步做什么

NI 消费到达的 flit。非尾 flit 被消费后返回普通 credit；TAIL 或 HEAD_TAIL 表示一个包的传输到达末尾。目标协议队列可接收且本周期交付条件允许时，NI 将消息入队，返回带 free signal 的 credit，更新统计并释放 flit 对象。

如果队列满或本周期交付机会已用完，尾 flit 进入 stall queue，等待后续交付机会。此时网络传输已到端点，但协议控制器尚不能据此继续执行。

源码：[NetworkInterface.cc](../../../src/mem/ruby/network/garnet/NetworkInterface.cc)，重点读 wakeup、flitisizeMessage、calculateVC、scheduleOutputLink、checkStallQueue。

## 3. Router：让 flit 逐跳前进

### 3.1 内部结构

```text
输入 Link → InputUnit / 输入 VC → SwitchAllocator → CrossbarSwitch → 输出 Link
                    │                    ↑
                RoutingUnit         OutputUnit：下游 VC 状态与 credit
```

InputUnit 缓冲 flit，包头计算方向；SwitchAllocator 检查下游资源和消息顺序，决定赢家；CrossbarSwitch 将赢家送往对应输出。OutputUnit 跟踪下游 VC 可否分配、还有多少空槽。

### 3.2 一条包头的处理路径

假设 HEAD 从 West 输入 VC2 进入，要向 East：

1. 输入 VC2 从 IDLE 转为 ACTIVE，计算并保存 outport=East。
2. flit 等到可参与交换仲裁的时间；多周期 Router 会推迟该时间。
3. 检查 East 对应 VNet 是否有空闲下游 VC。
4. 输入级仲裁选择一个 VC 提交请求，输出级仲裁选择获胜输入。
5. 为包分配下游 VC，例如 VC7，扣减其 credit，发出 HEAD。
6. BODY/TAIL 沿用保存的输出方向和 VC7，无须每个 flit 重新计算路由。

VC2 是本跳输入资源，VC7 是下游输入资源；包每跳可以使用不同 VC 编号。尾 flit 离开本跳输入 VC 后，本跳释放该输入 VC，并通知上游。

### 3.3 路由计算与仲裁的区别

路由计算回答“想去哪一个输出”，仲裁回答“本周期谁能使用它”。两个输入都想去 East，即使方向已经确定，也只能按该输出的能力先后服务。若分别去 East 和 North，则可能同周期并行传输。

Router 内的等待可能来自流水线尚未就绪、没有空闲下游 VC、没有 credit、顺序约束或仲裁失败。排查延迟时必须区分这些原因。

源码：[Router.cc](../../../src/mem/ruby/network/garnet/Router.cc)、[InputUnit.cc](../../../src/mem/ruby/network/garnet/InputUnit.cc)、[RoutingUnit.cc](../../../src/mem/ruby/network/garnet/RoutingUnit.cc)、[SwitchAllocator.cc](../../../src/mem/ruby/network/garnet/SwitchAllocator.cc)、[CrossbarSwitch.cc](../../../src/mem/ruby/network/garnet/CrossbarSwitch.cc)。

## 4. NetworkLink：传输 flit 并安排到达时间

### 4.1 链路怎样工作

NetworkLink::wakeup 从源队列取一个就绪 flit，将其到达时间设为链路时钟下的 latency 之后，放入链路内部缓冲，并安排消费者在该时刻唤醒。如果源队列仍有内容，会安排下一周期继续处理。

因此 link latency 表示传输延迟，不直接表示发送间隔。基础同频配置中，持续有数据且流控允许时，可以逐周期发送一个 flit，即使单个 flit 经过链路需要多个周期。

### 4.2 延迟与带宽的例子

假设链路 latency=3，每周期接受一个 flit，无下游阻塞：

| 周期 | 接受 | 到达下游 |
|---|---|---|
| 0 | H | — |
| 1 | B | — |
| 2 | T | — |
| 3 | — | H |
| 4 | — | B |
| 5 | — | T |

这张表只计链路接收后的过程，不含 NI/Router 的输出安排延迟。若宽度为 16B、频率为 1GHz且每周期一 flit，单方向原始带宽为 16GB/s；有效负载吞吐量还受协议开销、包尾填充、竞争和流控影响。

源码：[NetworkLink.cc](../../../src/mem/ruby/network/garnet/NetworkLink.cc)、[GarnetLink.py](../../../src/mem/ruby/network/garnet/GarnetLink.py)。

## 5. CreditLink：反馈下游可用缓冲

### 5.1 为什么不能无限往链路里塞 flit

即使链路空闲，下游输入 VC 也可能已满。若上游继续发送，就会超出模型允许的缓冲容量。credit 让发送方预先知道还能为多少个 flit 预留位置。

发送一个 flit 时，上游扣减一个 credit；下游移出一个 flit 时，产生一个返回 credit；该 credit 经 CreditLink 到达后，上游才增加额度。下游空槽已经释放但反馈还在路上时，上游仍需等待。

### 5.2 普通 credit 与 free signal

| 反馈 | 更新的含义 |
|---|---|
| 普通 credit | 下游多出一个缓冲槽，但 VC 仍可能属于原包 |
| 带 free signal 的 credit | 返还一个额度，并表示原包已离开，可重新分配该 VC |

尾 flit 已在上游发出，不代表下游 VC 已释放；需要等待下游消费尾 flit 后生成的反馈。credit 也不等于 MSI InvAck，后者表示副本已经失效。

### 5.3 它与 NetworkLink 的实现关系

本地 CreditLink 继承 NetworkLink，复用按时钟与延迟传递对象的机制；传递的是 Credit 对象。类定义短不表示它不影响性能，反馈延迟会影响额度循环和链路利用率。

例如下游 VC 深度为 2，上游连续发出 H、B 后额度归零。在收到某个返回 credit 之前，即使还剩一个 TAIL 待发且数据链路空闲，也必须停止发送。多个 VC 可以共享链路，但每个 VC 的额度仍需分别维护。

源码：[CreditLink.hh](../../../src/mem/ruby/network/garnet/CreditLink.hh)、[Credit.hh](../../../src/mem/ruby/network/garnet/Credit.hh)、[OutputUnit.cc](../../../src/mem/ruby/network/garnet/OutputUnit.cc)。

## 6. GarnetNetwork：把局部组件组成完整网络

### 6.1 配置、初始化和数据传输分属不同层次

Python 配置先创建 GarnetNetwork、Router、Link 和 NI 等对象，并给出拓扑、宽度、延迟与 VC 参数。不能理解成 C++ GarnetNetwork 独自创建并决定所有对象。

GarnetNetwork 的初始化将控制器的发送/接收队列注册到对应 NI，并根据拓扑组织连接：

| 入口 | 作用 |
|---|---|
| init | 将各节点的 toNet/fromNet 队列交给 NI |
| makeExtInLink | 建立从端点侧进入 Router 的连接 |
| makeExtOutLink | 建立从 Router 到端点侧的连接 |
| makeInternalLink | 建立 Router 之间的连接 |

GarnetNetwork 还提供目标 NI 到 Router 的映射、VNet 类型等信息，以及网络级统计。NI 用这些信息构造 RouteInfo，Router 用路由信息选择下一跳。

### 6.2 为什么它不是中心转发器

连接建好后，消息由各组件按事件和就绪时间局部推进。不会每经过一跳都先将 flit 送回 GarnetNetwork 再重新分发。它更像网络的组织与公共信息层，而转发工作分布在 NI、Router 和 Link 中。

源码：[GarnetNetwork.cc](../../../src/mem/ruby/network/garnet/GarnetNetwork.cc)、[GarnetNetwork.py](../../../src/mem/ruby/network/garnet/GarnetNetwork.py)、[通用网络配置](../../../configs/network/Network.py)。

## 7. Message、Packet 与 Flit 的关系

### 7.1 三个层次

| 层次 | 关心什么 | 例子 |
|---|---|---|
| 协议 Message | 一致性语义、地址、目标、数据 | 给 Cache0 返回地址 A 的 Data |
| 网络 Packet | 发往一个网络目标的一次包传输 | 从 Directory NI 到 Cache0 NI 的数据包 |
| Flit | 缓冲、交换、链路与流控单位 | H、B1、B2、B3、T |

当前实现不要求出现一个单独的 Packet C++ 对象才叫包。NI 为同一目标产生的一组 flit 具有共同的 packet_id、路由和消息引用，共同表示一个包。

### 7.2 包长怎样计算

在同宽路径的基础例子中：

```text
flit 数 N = ceil(消息建模字节数 / 输出端口每 flit 字节数)

控制消息：ceil(8B / 16B) = 1
数据消息：ceil((64B 数据 + 8B 开销) / 16B) = 5
```

计算依据是 MessageSize 类别映射的建模大小，不是宿主机上 C++ 消息对象的 sizeof。64B cache line、8B 控制开销与 16B 宽度是本例假设，不是所有配置的固定值。

### 7.3 HEAD、BODY、TAIL 分别做什么

```text
单 flit 包：HEAD_TAIL
5-flit 包：HEAD → BODY → BODY → BODY → TAIL
```

HEAD 建立当前跳的输出方向和 VC 关联；BODY 沿用关联并按 credit 前进；TAIL 标记包结束，触发相应 VC 释放与接收完成逻辑。HEAD_TAIL 在一个 flit 中同时承担头与尾的职责。

包的多个 flit 可以分布在多个 Router 和链路上，前面的 flit 不必等整个包到齐才向下一跳前进。4-flit 深度的 VC 可以承载经过它的 5-flit 包，只要前面的 flit 移出后及时返还 credit。

## 8. 从协议消息到 Flit：一次完整拆分

假设 Directory 返回单目标 Data，建模大小 72B，NI 输出宽度 16B，采用 VNet 2；下列编号仅为示意：

```text
协议消息 M：addr=A，Type=Data，Destination={Cache0}
  ↓ 源 NI：映射目标，申请本 VNet 的空闲 VC
网络包 P：packet_id=42，目标 NI=Cache0 对应的 NI
  ↓ ceil(72/16)=5
F0：HEAD ─┐
F1：BODY  │
F2：BODY  ├─ 共同的 packet_id、消息引用与目标
F3：BODY  │
F4：TAIL ─┘
```

flit 在 NI 的输出缓冲等待，各自逐周期竞争发送机会；到每个 Router 后，包头选择下一跳，整个包沿本跳保存的输出方向前进。不同包可在不同 VC 中交错使用物理链路，而同一包的 flit 保持协议传输所需顺序。

如果是 Destination 含三个 Sharer 的 Inv，则 NI 拆成三个单播包，每个包再按大小拆成自己的 flit。这说明“一条协议消息 → 一个 Packet → 多个 Flit”只对单目标基础情况成立；多播首先发生目标维度的复制。

## 9. 到达目标后怎样“重组”

### 9.1 真实硬件与本模拟实现的区别

真实网络需要接收并组合传输的数据位。当前 Garnet 用 flit 模拟传输粒度、占用和时序，每个 flit 持有协议消息的引用。flit 化不是将 C++ 消息对象序列化成一堆原始字节数组，接收端也不必逐字节恢复一个新对象。

基础路径中，NI 消费非尾 flit并返回 credit，尾 flit 到达且可以交付时，通过它的消息引用将协议消息放入接收 MessageBuffer。这在模型意义上表示整个包已经到达并完成重组/交付。

### 9.2 用 5-flit 包看接收事件

| 接收事件 | 目标 NI 做什么 | 是否向协议队列交付消息 |
|---|---|---|
| H 到达 | 消费 flit，返回普通 credit | 否 |
| B1/B2/B3 依次到达 | 各自消费并返回普通 credit | 否 |
| T 到达，队列可接收 | 将消息入队，返回 free credit | 是 |
| T 到达，队列不可接收 | 保留在 stall queue，推迟尾部释放 | 暂时否 |
| 后续目标队列有空位 | 重试交付，成功后释放尾部并返回 free credit | 是 |

协议消息入队还带有就绪延迟；目标控制器需要在队列可读时解码消息、触发事件，才能执行状态转换。NI 交付 Data 不等于 CPU 已经完成访存，缓存也可能仍需等待 InvAck。

### 9.3 重新串联五个组件

1. GarnetNetwork 提供队列绑定、目标映射和拓扑连接。
2. 源 NI 将协议消息转成一个或多个包，并拆成 flit。
3. Router 逐跳决定方向、资源与发送机会。
4. NetworkLink 传递 flit，CreditLink 反向反馈缓冲和 VC 释放。
5. 目标 NI 根据包完成边界交付消息，协议控制器继续执行。

## 10. 阅读与自检

建议先读 NetworkInterface::flitisizeMessage，再沿 Router::wakeup、InputUnit、SwitchAllocator、CrossbarSwitch 和 NetworkLink::wakeup 前进，最后回到目标 NI 的接收分支与 checkStallQueue。

完成后应能回答：

- 一条多播协议消息为什么可能产生多个包？每个包的 flit 数由什么决定？
- 目标控制器编号、NI 编号、Router 编号和 VC 编号分别是什么层次？
- 为什么 HEAD 已到达目的地，还不能向控制器交付整个包？
- 为什么有空闲链路，却可能因为没有 credit 而停止发送？
- 为什么普通 credit 不代表 VC 已可分配给新包？
- 为什么当前实现的“重组”不需要逐字节复制所有 flit 的内容？

后续详细的等待、时序、仲裁和性能影响见[核心知识点详解](garnet_core_concepts.md)。教学 MSI 当前默认使用 SimpleNetwork；本篇描述的是接入 Garnet 后的数据路径，实际配置切换见[MSI 消息发送链路](msi_ruby_network.md)。
