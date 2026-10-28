# Garnet 2.0 官方章节顺序导读

> 来源：[gem5 官方 Garnet 2.0 页面](https://www.gem5.org/documentation/general_docs/ruby/garnet-2/)，核对日期：2026-10-28。
> 本文按原页面正文标题的先后顺序编排，保留英文标题以便对照阅读；“官网要点”是简要概括，“本仓库说明”依据本地源码补充。本文不是全文逐句翻译，也不将本地扩展当作原文内容。
> 原有 [Garnet 导读与源码地图](garnet.md) 保留，适合按学习路线阅读；本篇适合在阅读官网时按章节查阅。

## 1. Garnet2.0: An On-Chip Network Model for Heterogeneous SoCs

**官网要点：**介绍模型背景、周期级建模定位和论文引用入口。

**本仓库说明：**Garnet 是 Ruby 可选的详细互连模型。协议控制器决定发送什么消息，Garnet 模拟缓冲、路由、仲裁和链路传输。网络延迟会反过来改变协议事务的完成时间。

本地代码位于 [src/mem/ruby/network/garnet/](../../../src/mem/ruby/network/garnet/README.txt)，该 README 标题写作 Garnet3.0。阅读官网的 Garnet 2.0 介绍时，应区分基础机制与当前版本已有的异构扩展。

原页面给出了 2009 年 GARNET 论文信息，研究引用请到原页面核对；这里不把本篇笔记作为模型论文的替代引用。

## 2. Invocation — 启用方式

**官网要点：**给出选择 Garnet 网络的入口。

**本仓库说明：**[configs/network/Network.py](../../../configs/network/Network.py) 的命令行 choices 是 simple/garnet。当前使用这一配置框架的脚本应选择：

```text
--network=garnet
```

官网这一页仍使用旧写法 `--network=garnet2.0`；不要直接复制到所有当前脚本。教学 Part 3 的 msi_caches.py 还直接创建 SimpleNetwork，未自动接入通用网络参数流程，单加上述选项并不能切换它的网络。

## 3. Configuration — 配置

**官网要点：**列出通用网络参数及 Garnet 专属参数。

**本仓库说明：**以下表格按本地定义整理，查看 [Network.py](../../../src/mem/ruby/network/Network.py)、[GarnetNetwork.py](../../../src/mem/ruby/network/garnet/GarnetNetwork.py) 和 [命令行初始化](../../../configs/network/Network.py)。

| 参数 | 本地含义/默认值 | 阅读提示 |
|---|---|---|
| number_of_virtual_networks | VNet 数量，由系统与协议配置 | 不要将 MSI 的 3 当作所有协议的固定值 |
| control_msg_size | 控制消息建模大小，默认 8B | 不是 C++ 消息对象 sizeof |
| ni_flit_size | 默认 16B | 命令行 link-width-bits 使用 bit，初始化时换成 byte |
| vcs_per_vnet | 默认 4 | 每个 VNet 的 VC 数 |
| buffers_per_data_vc | 默认 4 flit | 数据类 VC 的输入缓冲深度 |
| buffers_per_ctrl_vc | 默认 1 flit | 控制类 VC 的输入缓冲深度 |
| routing_algorithm | 默认 0，可选 0/1/2 | 查表 / XY / 自定义 |

本地 NI 按消息建模大小除以输出端口字节宽度并向上取整计算 flit 数。64B 数据、8B 开销、16B flit 对应 5 flit；改变块大小或宽度后需重算。

官网关于统一宽度及缓冲深度范围的旧描述不能当作当前全部实现的通用约束。本地还有 NetworkBridge 支持变宽与跨时钟域；更深的缓冲是否有意义，应结合包长、资源模型和实验目的分析，而不是将 5 当作所有数据 VC 的永久上限。

## 4. Topology — 拓扑

**官网要点：**说明拓扑、端口方向命名和网络组件。

**本仓库说明：**先查看 [Mesh_XY.py](../../../configs/topologies/Mesh_XY.py) 如何实例化 Router 与链路，再查看 [Topology.cc](../../../src/mem/ruby/network/Topology.cc) 如何建立连接和路由信息。

### 4.1 端口命名与延迟

src_outport 表示链路源 Router 的输出方向，dst_inport 表示目标 Router 的输入方向。例如本地 Mesh 中，从西侧 Router 向东侧邻居发送时，使用源输出 East、目标输入 West。以本地拓扑的实际赋值为准，不机械照搬页面中的方向示例。

拓扑可逐 Router/Link 设置延迟；网络默认参数和实例覆盖值需一起核对。拓扑决定连接是否存在，路由算法决定如何选择这些连接。

### 4.2 Network Components — 网络组件

| 组件 | 本仓库中的阅读重点 |
|---|---|
| GarnetNetwork | 将端点队列交给 NI，组织拓扑连接、映射与网络统计 |
| NetworkInterface | 协议消息与包/flit 的转换，注入及接收流控 |
| Router | 输入缓冲、输出方向、仲裁、VC 分配和交换 |
| NetworkLink | 按链路时钟和延迟传递 flit |
| CreditLink | 沿反方向传递缓冲额度和 VC 释放信息 |

Python 配置也参与对象创建，不能将 GarnetNetwork 理解为独自创建并控制所有对象的中央转发器。组件间协作详见[五个核心组件专题](garnet_components_and_flits.md)。

## 5. Routing — 路由

**官网要点：**讨论查表、自定义路由和多播处理。

**本仓库说明：**[RoutingUnit.cc](../../../src/mem/ruby/network/garnet/RoutingUnit.cc) 中的路由行为应按当前代码理解：

- 算法 0 匹配可达目标并选择最小权重候选；ordered VNet 取首个等权候选，unordered VNet 可随机选等权候选。原页面的确定性概括不足以描述这一差别。
- 算法 1 使用 XY；需要合适的 Mesh 坐标及端口方向信息。
- 算法 2 调用自定义入口，需要实现对应逻辑，不能只改参数就获得自适应路由。

链路权重影响选路，链路 latency 影响时序，两者不同。NI 的 flitisizeMessage 将多目标消息转换成多个单播包，并非在每个 Router 内做硬件多播复制。

## 6. Flow Control — 流量控制

**官网要点：**说明 VC 流控及控制/数据类别。

**本仓库说明：**一个输入 VC 保存当前包的状态，不要求完整包同时装入缓冲。包头建立输出关联，后续 flit 沿用关联；TAIL 离开后才触发该输入 VC 的释放。

上游维护下游 VC 的 credit。发送一个 flit 扣一个额度，收到反馈后补回；没有额度就停止。与物理链路共享、背压和协议 Ack 的区别见[核心知识点第 7～9 节](garnet_core_concepts.md)。

## 7. Router Microarchitecture — 路由器微架构

**官网要点：**按功能阶段介绍路由器，并说明多周期配置。

**本仓库说明：**对照 Router::wakeup、InputUnit 和 SwitchAllocator，可以按下面顺序阅读：

| 功能 | 本地实现与关键条件 |
|---|---|
| BW：写入缓冲 | InputUnit 消费到达 flit，存入输入 VC |
| RC：路由计算 | HEAD/HEAD_TAIL 计算输出方向并保存在 VC 中 |
| SA：交换分配 | 输入端先选候选，输出端再选赢家 |
| VS：输出 VC 选择 | 合入交换分配逻辑；包头需要空闲下游 VC |
| ST：穿越交换结构 | CrossbarSwitch 将赢家放入输出路径 |
| LT：链路传输 | NetworkLink 安排下游到达时间 |

router latency=1 时，可就绪 flit 在同一周期参与 SA/ST；不是每个功能阶段都独占一个周期。latency 大于 1 时，InputUnit 主要通过推迟 latency−1 周期的 SA 就绪时间建模额外处理时间。

ordered VNet 的实现是轮询配合 send_allowed 的顺序检查，不宜将原页面的有序仲裁描述直接理解成一个全网络 FIFO。端到端延迟还包含 NI、序列化、链路和竞争。

## 8. Buffer Management — 缓冲管理

**官网要点：**按端口、VNet、VC 组织缓冲并使用 credit。

**本仓库说明：**若有 V 个 VNet、每个 C 个 VC，则一个输入端口有 V×C 个 VC。缓冲深度单位是 flit，不是 byte，也不是包数；控制类和数据类 VC 深度分别配置。

普通 credit 只返还一个槽位；带 free signal 的 credit 还告诉上游该 VC 可重新分配。缓冲暂时空了不等于 VC 已空闲，因为同一包的后续 flit 可能还在上游。

增加 VC 或每 VC 深度会改变资源预算。比较性能时，应同时记录缓冲槽数、宽度、频率和负载，不能只报告某个参数变大后延迟下降。

## 9. Lifecycle of a Network Traversal — 一次网络传输的生命周期

**官网要点：**按各组件的 wakeup 展示执行链。

**本仓库说明：**沿源端到目标的处理顺序，核对以下函数；这是代码路径摘要，不是固定周期数表。

| 阅读顺序 | 入口 | 本地需要跟踪的行为 |
|---|---|---|
| 1 | NetworkInterface::wakeup | 检查发送队列、flit 化、输出调度；也处理接收及 credit |
| 2 | NetworkLink::wakeup | 从源队列取 flit，安排按延迟到达消费者 |
| 3 | Router::wakeup | 依次处理输入、输出、交换分配和 Crossbar |
| 4 | InputUnit::wakeup | 包头选方向、输入 VC 缓冲、安排 SA 就绪时间 |
| 5 | OutputUnit::wakeup | 消费 credit，增加额度，遇 free signal 标记输出 VC 空闲 |
| 6 | SwitchAllocator::wakeup | 两级仲裁、输出 VC 分配、扣额度、发送 flit、返还上游 credit |
| 7 | CrossbarSwitch::wakeup | 将获胜 flit 放入对应输出链路队列 |
| 8 | NetworkLink::wakeup | 继续下一跳传输，或交给目标 NI |

当前 SwitchAllocator 对每个获胜发送的 flit 都扣减 credit，包括包头；不要将原页面仅在 BODY/TAIL 项下提到扣额度理解为 HEAD 不消耗缓冲。

目标 NI 消费非尾 flit；尾 flit 可交付时把其消息引用放入协议队列，队列满则暂存尾 flit。这里的“重组”是模型中的完整包交付，不是逐字节拼装一个 C++ 消息对象。

源码入口：[NetworkInterface.cc](../../../src/mem/ruby/network/garnet/NetworkInterface.cc)、[Router.cc](../../../src/mem/ruby/network/garnet/Router.cc)、[SwitchAllocator.cc](../../../src/mem/ruby/network/garnet/SwitchAllocator.cc)、[NetworkLink.cc](../../../src/mem/ruby/network/garnet/NetworkLink.cc)。

## 10. Running Garnet2.0 with Synthetic Traffic — 使用合成流量

**官网要点：**引导到独立的合成流量教程。

**本仓库说明：**本节原页面只给教程入口，不是一份完整构建实验。进一步阅读[官方合成流量教程](https://www.gem5.org/documentation/general_docs/ruby/garnet_synthetic_traffic/)，并对照 [garnet_synth_traffic.py](../../../configs/example/garnet_synth_traffic.py) 和 [Garnet_standalone.py](../../../configs/ruby/Garnet_standalone.py)。

独立流量测试需要匹配 Garnet_standalone 协议构建；教学 MSI 默认 SimpleNetwork 的配置不是同一个实验系统。建议从单源单目标低负载开始，再扫描注入率并记录接收吞吐量与延迟。本文未执行这些实验，不提供已验证的运行结果。
