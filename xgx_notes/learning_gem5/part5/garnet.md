# Part 5 · 第 1 章：Garnet 官方文档导读与本仓库源码地图

> 前置阅读：[Ruby/SLICC](../part3/ruby_slicc.md)、[消息与 MessageBuffer](../part3/ruby_message_source.md)、[配置与运行](../part3/config_and_run.md)。
> 官方入口：[Garnet 2.0](https://www.gem5.org/documentation/general_docs/ruby/garnet-2/)。整理日期：2026-10-27。
> 本文围绕官方页面的主题组织学习路线；具体参数、执行流程和版本差异依据本仓库源码整理，不是逐字翻译。文中的实验是后续操作建议，本次未执行构建或仿真。

## 1. 官方页面先读什么

官方页面介绍 Garnet 在 Ruby 中的详细网络模型定位，并依次讨论配置、拓扑、路由、流控、路由器微架构和消息传输过程，最后给出合成流量入口。建议先读网络组件和传输生命周期，再回看流水线与参数；这样更容易把它与 Part 3 的协议消息联系起来。

论文引用入口也在原页面；若研究成果使用 Garnet，应按实际使用的模型查阅对应论文。当前实现的扩展背景另见 [HeteroGarnet](https://www.gem5.org/documentation/general_docs/ruby/heterogarnet/)。

后续章节以本地代码为依据补充解释，并指出不能直接照搬旧页面的地方。

## 2. 从 MSI 到 Garnet：研究问题怎样变化

在 MSI 中，GetM 会触发哪些状态转换由协议控制器决定；Garnet 模拟消息传输中的路由、缓冲、仲裁和链路延迟。

```text
发送控制器
  → 输出 MessageBuffer
  → NetworkInterface：转换成包和 flit，申请注入 VC
  → NetworkLink → Router → NetworkLink → Router
  → 目标 NetworkInterface：恢复协议消息
  → 输入 MessageBuffer
  → 接收控制器：解码为事件，执行协议状态转换

相邻节点之间还有反向 CreditLink，反馈缓冲可用情况。
```

网络送达 Data 不等于 CPU Store 已完成：缓存可能仍等待 InvAck；目标 MessageBuffer 暂时无空间也会推迟消息交付。需要同时区分协议条件、网络条件与控制器输入队列条件。

## 3. 先统一术语

| 名词 | 在本模型中的作用 | 易混淆点 |
|---|---|---|
| Message | 控制器产生的 Ruby 协议消息 | 不是 CPU 的一次访存请求本身 |
| Packet | 发往一个目标的一次网络传输 | 多播消息可能生成多个单播包 |
| Flit | 链路传输和缓冲管理的单位 | 一个包可以有多个 flit |
| HEAD / BODY / TAIL | 包的头、中间部分和尾 | 单 flit 包使用 HEAD_TAIL |
| VNet | 协议定义的逻辑流量类别 | MSI 的请求/转发/响应分组属于这一层 |
| VC | 每个 VNet 下独立跟踪包状态的虚拟通道 | 多个 VC 共享物理输出链路 |
| Credit | 下游反馈的空闲缓冲额度 | 不是 MSI 的 InvAck/PutAck |
| NI | 控制器消息队列与 flit 网络之间的接口 | 一个 Router 可以连接多个 NI |

一个 VC 在某时刻服务一个包，不要求整个包同时装进缓冲。长包可以一边前进、一边等待后续 flit；缓冲深度小于包长不等于不能发送。

## 4. 本仓库参数与版本差异

核对入口：[GarnetNetwork.py](../../../src/mem/ruby/network/garnet/GarnetNetwork.py)、[网络参数与初始化](../../../configs/network/Network.py)、[通用 Network.py](../../../src/mem/ruby/network/Network.py)。

| 参数 | 当前默认值/选项 | 理解方式 |
|---|---|---|
| `--network` | 默认 simple；Garnet 选 `garnet` | 当前命令行 choices 接受 simple/garnet |
| `--router-latency` | 1 | 路由器处理延迟，可由拓扑逐路由器覆盖 |
| `--link-latency` | 1 | 链路延迟，可逐链路覆盖 |
| `--link-width-bits` | 128 bit | 初始化时除以 8，映射到 NI 的字节宽度 |
| `ni_flit_size` | 16 byte | Python 网络对象中的 flit 大小 |
| `--vcs-per-vnet` | 4 | 每个 VNet 的 VC 数 |
| `buffers_per_data_vc` | 4 flit | 数据类 VC 的缓冲深度 |
| `buffers_per_ctrl_vc` | 1 flit | 控制类 VC 的缓冲深度 |
| `--routing-algorithm` | 0/1/2 | 查表 / XY / 自定义入口 |
| `--garnet-deadlock-threshold` | 50000 | NI 中长时间无法申请 VC 的检测阈值，不是无死锁证明 |

缓冲深度是网络对象参数，当前脚本没有对应的同名命令行开关。实际 VNet 数量及用途由所用协议与网络配置共同决定，不能把 MSI 的三个 VNet 当作所有协议的固定定义。

`NetworkInterface::flitisizeMessage()` 根据消息大小和输出端口宽度向上取整得到 flit 数。在 64B cache line、8B 控制开销和 16B flit 的常见设置下，控制消息为 1 flit，数据消息为 ceil(72/16)=5 flit。换块大小、消息类别或链路宽度后必须重新计算。

官方页面中的 `garnet2.0/` 路径在本仓库对应 `garnet/`；本地 README 标题为 Garnet3.0。旧页面对统一链路宽度的说明不能直接覆盖当前异构实现：本地还有 [NetworkBridge.cc](../../../src/mem/ruby/network/garnet/NetworkBridge.cc) 与 SerDes/时钟域交叉支持。初学阶段先固定宽度与时钟，再研究这些扩展。

## 5. 拓扑决定连接，路由决定方向

先读 [Mesh_XY.py](../../../configs/topologies/Mesh_XY.py) 和 [Topology.cc](../../../src/mem/ruby/network/Topology.cc)：前者创建路由器与链路，后者参与构造路由信息。端口方向名称由拓扑提供给路由器。

然后读 [RoutingUnit.cc](../../../src/mem/ruby/network/garnet/RoutingUnit.cc)：

- 算法 0 查询路由表，在可达候选中按最小权重选择。ordered VNet 取首个等权候选；unordered VNet 可随机选择等权候选。因此不应将当前默认行为统称为严格确定性路由。
- 算法 1 调用 XY 路由，依赖 Mesh 行列与端口方向信息。建立 Mesh 拓扑不意味着命令行算法参数自动变成 1。
- 算法 2 是自定义路由入口；先实现 `outportComputeCustom()`，再启用该选项。

链路权重参与路径选择，链路 latency 表达传输延迟，两者不能混为同一个参数。修改路由时还要检查通道依赖和协议要求的消息顺序。

NI 会将多目标消息拆成多个单播包。MSI 中一次向多个 Sharer 失效，可能产生多个网络包，而不是网络内部自动复制一个包到所有出口。

## 6. Router 的一次处理怎样展开

入口：[Router.cc](../../../src/mem/ruby/network/garnet/Router.cc) 的 `wakeup()` 依次处理输入单元、输出单元、交换分配与交叉开关。

| 阶段 | 本地实现入口 | 需要跟踪的状态 |
|---|---|---|
| 输入缓冲 BW | InputUnit::wakeup | flit 对应哪个输入 VC |
| 路由计算 RC | InputUnit → Router → RoutingUnit | HEAD/HEAD_TAIL 计算输出端口，后续 flit 沿用 |
| 输入仲裁 SA-I | SwitchAllocator::arbitrate_inports | 每个输入端口选出一个可请求的 VC |
| 输出仲裁 SA-II 与 VC 选择 | SwitchAllocator::arbitrate_outports | 输出端口选择赢家；包头需要可分配的输出 VC |
| 交换穿越 ST | CrossbarSwitch::wakeup | 赢家进入对应输出链路 |
| 链路传输 LT | NetworkLink::wakeup | 按链路延迟到达下游 |

本地将 VC 分配合入 SwitchAllocator，不是独立的 VCAllocator 阶段。ordered VNet 还要检查同方向较早到达的包，不能只用轮询描述全部仲裁规则。

默认 router latency 为 1 时，flit 到达输入后可在当周期参与 SA/ST；链路继续承担传输延迟。router latency 大于 1 时，InputUnit 将 flit 的 SA 就绪时间推迟 latency−1 个周期。这是增加可参与仲裁前的等待，不是重新实现了每一级独立流水寄存器。

端到端延迟还包括 NI、包序列化、链路和争用；“1 周期路由器”不等于一个包跨多个路由器只用 1 周期。

## 7. Credit 怎样限制发送与释放 VC

跟踪 [InputUnit.cc](../../../src/mem/ruby/network/garnet/InputUnit.cc)、[OutputUnit.cc](../../../src/mem/ruby/network/garnet/OutputUnit.cc)、[SwitchAllocator.cc](../../../src/mem/ruby/network/garnet/SwitchAllocator.cc)。

1. 上游 OutputUnit 保存下游 VC 的可用额度和分配状态。
2. 发送 flit 前检查可发送条件；包头还需要空闲的输出 VC。
3. 仲裁获胜并发出 flit 时，扣减对应输出 VC 的 credit；当前实现对包头、中间和尾 flit 都扣减。
4. 下游输入 VC 移出一个 flit，返还一个 credit，表示释放一个缓冲槽。
5. 如果移出的是 TAIL/HEAD_TAIL，返回 credit 同时携带 free signal。
6. 上游接到 free signal 后，才把该输出 VC 标记为空闲，供其他包使用。

“还有一个空闲缓冲槽”和“整个 VC 可以交给另一个包”是两件事。credit 本身也要经过链路和事件调度，不能认为释放槽位会瞬间反馈到上游。

## 8. 一个包的生命周期与源码阅读顺序

| 顺序 | 文件/函数 | 本轮阅读要回答的问题 |
|---|---|---|
| 1 | NetworkInterface::wakeup / flitisizeMessage | 从哪个 MessageBuffer 取消息，怎样选 VNet/VC，怎样拆多播？ |
| 2 | NetworkLink::wakeup | flit 何时交给消费者，何时安排唤醒？ |
| 3 | InputUnit::wakeup / VirtualChannel | 包头记录了哪些输出信息？flit 何时可参与仲裁？ |
| 4 | SwitchAllocator::send_allowed / arbitrate_outports | 没 VC、没 credit、顺序限制、竞争失败分别在哪里发生？ |
| 5 | CrossbarSwitch::wakeup | 获胜 flit 如何进入输出链路？ |
| 6 | OutputUnit::wakeup | 返回 credit 如何更新额度与 VC 状态？ |
| 7 | 目标 NetworkInterface::wakeup | 尾 flit 到达后如何向协议队列交付消息？队列满了怎么办？ |

这些组件使用事件驱动的 wakeup，按就绪时间推进；不是宿主机中的无限逐周期轮询循环。先在同频、同宽网络中追踪一个单 flit 包，再追踪一个多 flit 数据包。

补充源码入口：[GarnetNetwork.cc](../../../src/mem/ruby/network/garnet/GarnetNetwork.cc) 负责网络连接与统计，[本地 README](../../../src/mem/ruby/network/garnet/README.txt) 提供执行流程提示。

## 9. 从合成流量进入实验

实验入口是 [garnet_synth_traffic.py](../../../configs/example/garnet_synth_traffic.py)，配套 [Garnet_standalone.py](../../../configs/ruby/Garnet_standalone.py)。完整构建与流量参数见 [官方合成流量教程](https://www.gem5.org/documentation/general_docs/debugging_and_testing/directed_testers/garnet_synthetic_traffic/)。

这里先不复用 MSI 构建目录：合成流量需要 Garnet_standalone 协议，而本仓库 build_opts/NULL 默认使用 MI_example。准备独立构建时，应核对当前 Kconfig 的协议符号和最终构建配置。

建议依次完成：

1. 单源、单目标、低注入率：画出路由路径并解释跳数。
2. 固定 4×4 Mesh、宽度、VC、时钟和流量模式，扫描注入率，画吞吐量与延迟曲线。
3. 每次只改一个参数，例如 VC 数、链路宽度或路由器延迟，解释性能变化的原因。
4. 回到 MSI，分析 GetM/Inv/Data/InvAck 的竞争怎样延长控制器瞬态状态。

统计入口为 GarnetNetwork::regStats 和 NetworkInterface::incrementStats。关注 packets_injected、packets_received、average_packet_network_latency、average_packet_queueing_latency、average_packet_latency、average_hops，以及 flit 计数。

本地 incrementStats 用 Tick 差累计网络与排队时间；比较结果时应核对统计单位、时钟与转换方式。网络时间还包含网络内部争用，queueing 时间包含源侧等待与目标侧交付等待，不能简单理解为“network 只有链路时间”。

固定时长结束可能仍有在途流量，注入与接收数量不等不直接表示丢包。接收吞吐量应使用测量区间内的接收数除以对应时长，并说明是全网还是按节点归一化。VC 数增多通常也增加总缓冲资源，比较时记录资源预算。

## 10. 学完后的自检

- 能区分协议 Ack、缓冲 credit 和 VC free signal。
- 能解释为什么 5-flit 的包可以经过 4-flit 深度的 VC。
- 能指出 flit 因路由器延迟、输出 VC、credit、仲裁或目标队列而等待的位置。
- 能区分拓扑、路由算法、链路权重与链路延迟。
- 能把一次 MSI 事务的协议完成条件与网络传输完成条件分开解释。

后续扩展方向：自定义路由、公平性、拥塞与饱和、异构宽度/时钟桥接。先完成单包路径和基础流量曲线，再修改网络机制。
