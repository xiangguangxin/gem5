# Garnet Router 的两级交换仲裁与 Round-Robin 伪代码

> 前置阅读：[流控入门](garnet_flow_control_basics.md)、[核心知识点详解](garnet_core_concepts.md)。
> 本文对照当前仓库 SwitchAllocator 实现整理。伪代码省略统计、事件调度和部分接口细节；例子是手推示意，不是仿真日志。

## 1. 仲裁决定谁能在本轮通过

多个输入端口的 flit 可能同时请求同一个输出端口，但该输出在本轮不能同时服务所有请求，因此需要仲裁。

| 机制 | 回答的问题 |
|---|---|
| Routing | 当前包想去哪个输出端口？ |
| VC 分配与 Credit 流控 | 下游是否有可用资源，允许发送吗？ |
| Switch Arbitration | 具备条件的候选中，本轮谁通过 Crossbar？ |

Router 的交换仲裁主要由 [SwitchAllocator.cc](../../../src/mem/ruby/network/garnet/SwitchAllocator.cc) 实现，采用两级可分离仲裁，选择顺序基于 Round-Robin。

这里主要讨论 Router 的交换仲裁，不能由此推断 NI 调度或所有资源分配都采用完全相同的算法。

## 2. 两级分别选什么

### 2.1 SA-I：输入端口内部选 VC

每个输入端口有多个 VC，但本轮最多提交一个输出请求。仲裁器从该输入的 VC 轮询起点开始，扫描满足就绪时间、下游资源和顺序约束的候选。

```text
West 输入
├─ VC0 → East：没有 credit，跳过
├─ VC1 → North：满足条件，可选择
└─ VC2 → East：满足条件，但本轮可能未被选中
```

SA-I 选中的只是“代表该输入提交请求的 VC”，不代表已经获得 Crossbar。

### 2.2 SA-II：输出端口选择输入

每个输出端口从请求它的输入中轮询选择一个赢家。例如：

```text
West  ──请求──→ East
South ──请求──→ East
Local ──请求──→ North
```

East 在 West/South 中选一个；North 可以同时服务 Local。这样每输入最多提交一个请求、每输出最多选择一个输入，不冲突的传输可以并行。

包头若尚无输出 VC，获胜后在目标输出方向分配一个属于该 VNet 的空闲下游 VC，之后发出一个 flit。

### 2.3 两级不等于固定两个周期

SA-I 和 SA-II 是两层选择逻辑。本地 SwitchAllocator::wakeup 依次调用 arbitrate_inports 和 arbitrate_outports；默认模型中它们可在同一次唤醒中执行，不应直接按两个独立周期计算延迟。

## 3. Round-Robin 的轮询规则

Round-Robin 通过一个持久指针记录下一轮从哪里开始扫描，遇到末尾就回到开头：

```text
候选编号：0 → 1 → 2 → 3 → 0 → ...
当前起点：2
检查顺序：2、3、0、1
```

不具备发送条件的候选会被跳过。实际获胜后，下一次从赢家后一个位置开始。当前实现中，SA-I 选中但 SA-II 落选，不会因此推进该输入的 VC 轮询指针。

| 指针 | 每个对象有一份 | 本地字段 |
|---|---|---|
| VC 轮询起点 | 输入端口 | m_round_robin_invc[inport] |
| 输入端口轮询起点 | 输出端口 | m_round_robin_inport[outport] |

这些指针跨仲裁轮次保存，而本轮请求记录会在每次仲裁后清理。

## 4. 参与仲裁前检查什么

本地 send_allowed 主要检查：

1. 未建立下游 VC 关联的包头，需要目标输出方向上有空闲的同 VNet VC。空闲 VC 的初始化额度保证其首 flit 有可用槽位。
2. 已有下游 VC 关联的后续 flit，需要该 VC 的 credit 为正。
3. ordered VNet 中，不能越过同一输入、同 VNet 内更早到达且已就绪、请求同一输出的包。

流水线是否达到 SA 就绪时间由 need_stage 等逻辑检查。顺序限制是局部条件，不能理解成全网所有消息的全局 FIFO。

因此“轮询仲裁”不是无条件让每个 VC 严格轮流发送。无 credit、未就绪或受顺序限制的 VC 都可能继续等待。

## 5. 两级仲裁伪代码

### 5.1 状态与本轮记录

```text
持久状态：
    next_vc[input]       # 每个输入端口的 VC 扫描起点
    next_input[output]   # 每个输出端口的输入扫描起点

每轮临时状态：
    requested_output[input] = NONE
    chosen_vc[input] = NONE
```

本地初始化轮询起点为 0。下面的 VC 数指当前输入端口跨所有 VNet 的 VC 总数；可分配下游 VC 的范围仍必须属于相同 VNet。

### 5.2 SA-I：每个输入选一个可请求的 VC

```text
for 每个输入端口 input:
    for offset = 0 到 VC数量 - 1:
        vc = (next_vc[input] + offset) % VC数量

        if vc 中没有已就绪、可参与 SA 的 flit:
            continue

        output = vc 已保存的输出方向
        downstream_vc = vc 已保存的下游 VC

        if downstream_vc 尚未分配:
            if output 下没有属于当前 VNet 的空闲 VC:
                continue
        else:
            if 对应 downstream_vc 的 credit == 0:
                continue

        if 违反 ordered VNet 的顺序条件:
            continue

        requested_output[input] = output
        chosen_vc[input] = vc
        break   # 本输入本轮最多提交一个请求
```

这里不更新 next_vc，因为提交请求不代表实际获得发送机会。

### 5.3 SA-II：每个输出选一个输入

```text
for 每个输出端口 output:
    for offset = 0 到 输入端口数量 - 1:
        input = (next_input[output] + offset) % 输入端口数量

        if requested_output[input] != output:
            continue

        vc = chosen_vc[input]

        if vc 尚未分配下游 VC:
            downstream_vc = 分配一个同 VNet 的空闲下游 VC
            将 downstream_vc 关联保存在输入 vc 中
            将对应输出 VC 状态标为已占用
        else:
            downstream_vc = vc 已保存的下游 VC

        flit = 从输入 vc 的缓冲取出队首
        将 flit 的输出端口设为 output
        将 flit 携带的 VC 编号设为 downstream_vc

        对应 downstream_vc 的 credit -= 1
        将 flit 标为可进入 ST，交给 Crossbar

        if flit 是 TAIL 或 HEAD_TAIL:
            将当前输入 vc 标为空闲
            向上游生成 credit，free_signal = true
        else:
            向上游生成 credit，free_signal = false

        requested_output[input] = NONE

        # 只有实际获得交换机会才推进指针
        next_input[output] = (input + 1) % 输入端口数量
        next_vc[input] = (vc + 1) % VC数量

        break   # 本输出本轮最多选择一个赢家

清理本轮请求记录
根据后续就绪 flit 安排再次唤醒
```

credit 扣的是“当前 Router 跟踪的下游额度”；返回 credit 通知的则是“上游发送方，当前输入槽位已释放”。这两个方向不要混淆。

尾 flit 离开当前输入 VC，可释放这个输入 VC；当前输出方向的下游 VC 要等下游返回 free signal 后才能标为空闲。两者不是同一时刻的同一资源。

## 6. 具体例子：为什么会出现空闲输出

假设全部候选都满足资源、就绪和顺序条件：

```text
输入 I0：VC0 的 A → East
         VC1 的 B → North
输入 I1：VC0 的 C → East
```

若 SA-I 在 I0 选择 A、在 I1 选择 C：

```text
SA-I： I0 → East，I1 → East
SA-II：East 选择 I0，North 没有请求
结果：A 通过，B/C 等待，North 空闲
```

虽然 B 本来可以去 North，但 I0 本轮只提交了 A，SA-II 不会回头要求 I0 再提交 B。两级可分离选择不保证全局最大匹配。

下一轮 I0 的 VC 起点移到 VC1；I1 上轮落选，其指针保持原值。若资源仍充足：

```text
SA-I： I0 的 B → North，I1 的 C → East
SA-II：North 选择 I0，East 选择 I1
结果：两个 flit 并行通过
```

## 7. 公平性与吞吐量怎样理解

在两个输入持续具备发送资格、只竞争同一输出且无其他限制时，轮询可使它们交替获得机会。但端到端性能还受多跳竞争、credit、包长与顺序约束影响。

- 某流没有 credit 被跳过，不直接表示仲裁器偏心。
- 两个流获得相同 flit 数，不表示完成相同包数；长包需要更多次机会。
- 一次包头获胜不代表整包持续独占物理输出，后续 flit 仍需按条件仲裁。
- 增加 VC 增加候选和缓冲资源，不等于增加输出链路带宽。

## 8. 仲裁等待与背压的区别

| 等待原因 | 状态 | 需要什么变化 |
|---|---|---|
| 没有空闲下游 VC | 包头无法建立关联 | 下游 VC 释放并反馈 |
| 没有 credit | 已关联 VC 额度耗尽 | 下游槽位释放，返回 credit |
| 顺序约束 | 资源足够但不允许越过更早包 | 更早包推进 |
| 仲裁失败 | 具备发送资格但本轮竞争落选 | 后续轮次获得机会 |

这些原因可能先后出现。无 credit 或 VC 受阻可逐跳形成背压，而仲裁失败也会延长缓冲驻留时间，进一步增加竞争。

## 9. 源码阅读与自检

按以下顺序阅读 [SwitchAllocator.cc](../../../src/mem/ruby/network/garnet/SwitchAllocator.cc)：

| 函数 | 对应内容 |
|---|---|
| init | 初始化端口数量、轮询指针和本轮请求数组 |
| wakeup | 依次执行两级仲裁，再清理请求和安排后续处理 |
| arbitrate_inports | SA-I，按输入的 VC 指针轮询候选 |
| send_allowed | 下游 VC、credit 与 ordered VNet 检查 |
| arbitrate_outports | SA-II、转交 flit、扣/返 credit、更新指针 |
| vc_allocate | 为赢家选择下游空闲 VC，保存关联 |

配合 [SwitchAllocator.hh](../../../src/mem/ruby/network/garnet/SwitchAllocator.hh) 查看持久状态与数组。

自检：能解释 SA-I 赢家为什么仍会落选，为什么落选不推进 VC 指针，为什么两级不固定等于两周期，以及为什么 North 空闲时 B 仍可能无法在本轮通过。
