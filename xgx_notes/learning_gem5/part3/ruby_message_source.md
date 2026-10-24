# Part 3 · 专题源码解读：Message、MessageBuffer 与消息处理链路

> 前置阅读：[Ruby/SLICC 与消息](ruby_slicc.md)、[L1 缓存控制器](cache_controller.md)。本文对应当前仓库源码，以教学 MSI 为例。
> 阅读目标：知道消息是什么、存在哪里、何时可处理、谁被唤醒，以及为何有些消息需要重新等待。本文为源码静态解读，没有声称已经运行新的仿真或采集 trace。

## 1. 先区分四个对象

| 对象 | 负责什么 | 不应混淆的概念 |
|---|---|---|
| Message / 派生消息 | 保存消息内容及通用时间信息 | 一条消息不是一个事件队列 |
| MessageBuffer | 暂存消息，管理就绪时间、容量和阻塞消息 | 不负责执行 MSI 状态转换 |
| Consumer | 提供被定时唤醒的机制 | 唤醒表示获得处理机会，不代表消息一定完成 |
| 控制器的 in_port / action | 解析消息、触发状态机、执行协议动作 | SLICC 入口不是额外的 MessageBuffer |

正常路径可以顺着下面这条线读：

```text
创建消息 → enqueue 入队并设置就绪时间 → 安排 Consumer 的唤醒事件
    → 到达相应时钟边界 → 控制器检查 isReady → peek 读取
    → trigger 匹配 transition → action 决定处理、出队或继续等待
```

`mandatoryQueue`、`requestToDir`、`responseToDirOrSibling` 都是 MessageBuffer 实例的名字，而不是三个不同的队列实现类。它们存放不同消息、关联不同消费者，复用同一套底层队列机制。

## 2. 源码地图：除了 MessageBuffer，还需要读哪些文件

所有链接相对本文所在目录；按表中类名或函数名搜索即可定位，不依赖生成目录。

| 文件 | 重点看什么 |
|---|---|
| [Message.hh](../../../src/mem/ruby/slicc_interface/Message.hh) | Message 基类、MsgPtr、时间字段、消息比较运算符 |
| [RubyRequest.hh](../../../src/mem/ruby/slicc_interface/RubyRequest.hh) | CPU 本地访存请求的地址、类型、大小和关联 Packet |
| [MSI-msg.sm](../../../src/learning_gem5/part3/MSI-msg.sm) | RequestMsg / ResponseMsg 的协议字段及 functional 方法 |
| [MessageBuffer.py](../../../src/mem/ruby/network/MessageBuffer.py) | ordered、buffer_size、randomization、max_dequeue_rate 等配置参数 |
| [MessageBuffer.hh](../../../src/mem/ruby/network/MessageBuffer.hh) | 公开接口、正常消息堆、阻塞表和延迟入队表 |
| [MessageBuffer.cc](../../../src/mem/ruby/network/MessageBuffer.cc) | enqueue、isReady、dequeue、容量检查和阻塞恢复的实际逻辑 |
| [Consumer.hh](../../../src/mem/ruby/common/Consumer.hh)、[Consumer.cc](../../../src/mem/ruby/common/Consumer.cc) | EventFunctionWrapper、时钟对齐、schedule / reschedule 与 wakeup |
| [Sequencer.cc](../../../src/mem/ruby/system/Sequencer.cc) | issueRequest 创建 RubyRequest 并提交 mandatoryQueue |
| [MSI-cache.sm](../../../src/learning_gem5/part3/MSI-cache.sm) | in_port 读取消息、sendGetS 等动作入队、pop 动作出队 |
| [MSI-dir.sm](../../../src/learning_gem5/part3/MSI-dir.sm) | 对端目录如何收请求、生成响应和转发消息 |
| [msi_caches.py](../../../configs/learning_gem5/part3/msi_caches.py) | 创建 MessageBuffer 并将协议队列接入 Ruby 网络 |
| [EnqueueStatementAST.py](../../../src/mem/slicc/ast/EnqueueStatementAST.py) | SLICC enqueue 怎样转换为 C++ MessageBuffer 调用 |
| [StateMachine.py](../../../src/mem/slicc/symbols/StateMachine.py) | 生成控制器、为输入队列设置 Consumer，以及生成处理逻辑 |

先读 MessageBuffer 的公开接口和几个核心函数，再沿调用链向上下游展开，不必第一遍读完 SLICC 生成器。

## 3. Message：一条消息的公共基础

### 3.1 MsgPtr 是什么

源码中：

```cpp
typedef std::shared_ptr<Message> MsgPtr;
```

MessageBuffer 存的是共享指针，可以承载不同 Message 派生类型。基类使用虚析构函数及虚方法，让调用方通过统一接口处理具体消息。`clone()` 是复制消息的接口，不等于复制共享指针；后者只是让两个指针共同引用同一对象。

### 3.2 关键字段与方法

| 成员或方法 | 含义 |
|---|---|
| m_time / getTime() | 消息初始化时记录的时间，与每次入队的就绪时间分开保存 |
| m_LastEnqueueTime / getLastEnqueueTime() | 虽然名字叫“上次入队时间”，MessageBuffer 入队后会将其设为本段的 arrival_time，即消息最早可出队的时间 |
| m_DelayedTicks / updateDelayedTicks() | 累积所经历的延迟；按调用时刻减去上次记录时间更新，不宜直接当成整个 CPU 访存延迟 |
| m_msg_counter | 配合队列比较器，在就绪时间相同时确定消息顺序；不是全系统事务 ID |
| clone() / print() | 复制消息、输出消息内容，由派生类实现 |
| getDestination() / getMessageSize() | 网络需要的目的地及大小类别接口；基类默认实现会 panic，不能假定每种 Message 都可直接送入网络 |
| functionalRead() / functionalWrite() | functional 访问时查询或更新消息中的数据，具体能力由派生消息实现 |

**Message 不是 gem5 的 Event 子类。** 消息表示“传什么”，Consumer 持有的事件负责安排“什么时候获得处理机会”。

## 4. RubyRequest、RequestMsg、ResponseMsg：消息内容由谁定义

| 消息类型 | 表达什么 | 当前教学 MSI 的典型路径 |
|---|---|---|
| RubyRequest | CPU 要执行 LD / ST / IFETCH 等访存操作 | Sequencer → mandatoryQueue → mandatory_in |
| RequestMsg | 控制器之间的请求或控制消息 | GetS/GetM/PutS/PutM 走请求网络；转发 GetS/GetM、Inv、PutAck 走 forward 网络 |
| ResponseMsg | 一致性响应 | Data / InvAck 走响应网络 |

RubyRequest 是手写 C++ 类；RequestMsg / ResponseMsg 在 MSI-msg.sm 中定义，再由 SLICC 生成相应代码。它们共享消息框架，但字段和协议语义不同。

### 4.1 RubyRequest 的数据结构源码在哪里

类定义位于 [RubyRequest.hh:61](../../../src/mem/ruby/slicc_interface/RubyRequest.hh#L61)。头文件还包含构造函数、访问方法和 clone；打印与 functional 访问等方法实现在 [RubyRequest.cc](../../../src/mem/ruby/slicc_interface/RubyRequest.cc)。普通 CPU 请求的创建过程看 [Sequencer.cc](../../../src/mem/ruby/system/Sequencer.cc) 的 `Sequencer::issueRequest`。

以下只摘录主要字段，并补充阅读注释，不是完整类定义：

```cpp
class RubyRequest : public Message
{
  public:
    Addr m_PhysicalAddress;  // 本次访问的物理地址
    Addr m_LineAddress;      // 对应缓存行的起始地址
    RubyRequestType m_Type;  // LD、ST、IFETCH 等请求类型
    Addr m_ProgramCounter;  // 发起访问的指令地址
    RubyAccessMode m_AccessMode; // 访问模式
    int m_Size;             // 本次访问的字节数
    PacketPtr m_pkt;        // 关联原始 Packet，而不是复制整份数据
    WriteMask m_writeMask;  // 写掩码
    DataBlock m_WTData;     // 特定写入路径使用的数据字段
    // 还有预取、上下文、原子操作及事务相关字段等
};
```

| 字段 | 阅读时应注意什么 |
|---|---|
| m_PhysicalAddress | CPU 本次实际访问的位置，可以位于缓存行内部 |
| m_LineAddress | 构造时根据块大小由 makeLineAddress 计算，用于按缓存块查找 Entry/TBE |
| m_Type / m_Size | 表示操作类型与访问长度；访问 4 字节不代表缓存行只有 4 字节 |
| m_ProgramCounter | 发起访问的指令位置，不是目标数据地址 |
| m_pkt | 指向原始 gem5 Packet；写入内容、读取结果需要结合这个 Packet 和 Sequencer 的完成路径理解 |
| m_writeMask / m_WTData | 为相应写入路径提供掩码和数据；部分构造函数接受显式 DataBlock 和写掩码，不能推断普通 CPU 请求都会在 m_WTData 中复制完整缓存行 |

例如缓存行为 64 B、CPU 从 `0x104` 读取 4 B 时：`m_PhysicalAddress = 0x104`，`m_LineAddress = 0x100`，`m_Size = 4`。控制器按 `0x100` 管理缓存行，完成读取时再从行内偏移 4 的位置取出 4 字节。

### 4.2 RubyRequest 的实际读写数据在哪里

**RubyRequest 不等于一份完整缓存行数据。** 在当前普通 CPU / 教学 MSI 路径中，它主要描述访问并关联原始 Packet；缓存行内容保存在 Entry.DataBlk，读写完成时由 Sequencer 在 Packet 与缓存 DataBlock 之间传递相应字节。

| 操作 | 请求提交时 | 控制器具备完成条件后 |
|---|---|---|
| 读 / 取指 | 已知地址、大小和类型，但尚未取得读结果；RubyRequest 关联用于该访问的 Packet | 控制器调用 readCallback 并提供缓存 DataBlk，Sequencer 取出行内相应字节填入 Packet，再回应 CPU |
| 普通写 | 原始写 Packet 已携带待写数据，RubyRequest 记录访问并关联 Packet | 控制器取得写权限后调用 writeCallback，Sequencer 将 Packet 中的待写字节更新到缓存 DataBlock，再完成响应 |

教学协议中的回调可在 [MSI-cache.sm](../../../src/learning_gem5/part3/MSI-cache.sm) 的 `loadHit`、`externalLoadHit`、`storeHit`、`externalStoreHit` 等动作中找到；实际字节处理继续读 Sequencer 的 `hitCallback`。核心读写操作可概括为：

```cpp
// 读：从缓存行取出本次需要的字节，复制到 Packet。
pkt->setData(data.getData(getOffset(request_address), pkt->getSize()));

// 普通写：用写 Packet 的内容更新缓存 DataBlock。
data.setData(pkt);
```

上面是不同分支的摘录，不是连续执行的两条语句；原子操作、Swap、条件写等另有处理逻辑。以读取 X 的 4 字节为例，完整的数据路径是：

```text
RubyRequest：地址 X、大小 4、类型 LD、关联原始 Packet
    ↓
控制器准备好缓存行数据（命中，或缺失后接收 Data 并填入缓存）
    ↓
sequencer.readCallback(address, cache_entry.DataBlk, ...)
    ↓
Sequencer 按地址偏移取出 4 字节，填入原始 Packet
    ↓
向 CPU 返回读取响应
```

普通写则是“Packet 携带写入内容 → 协议取得所需权限 → Sequencer 更新 Entry 的 DataBlock”。不是只要 RubyRequest 进入 mandatoryQueue，数据就已经完成写入。请求出队后，Sequencer 仍需跟踪该访问直至完成，不能用队列是否为空判断 CPU 是否已收到结果。

### 4.3 RubyRequest.cc 的 functional 方法补充

当前实现的两种 functionalRead 都返回 false；functionalWrite 则检查数据是否存在等条件，并尝试更新关联 Packet 的数据。**这是 functional 访问的特殊处理，不代表普通 timing 读取不能返回数据。** timing 读取的返回路径是上一节的控制器回调与 Sequencer 数据复制，不能只看 RubyRequest::functionalRead 判断它。

### 4.4 跨网络的协议消息字段

RequestMsg 中重点看 `addr`、`Type`、`Requestor`、`Destination`、`DataBlk`、`MessageSize`。ResponseMsg 中还要看 `Sender` 和 `Acks`。`Requestor` 是原始请求发起者，`Sender` 是响应发送者，转发路径中两者并不一定相同。

`MessageSize` 是 Control / Data 等大小类别，不是直接填写一个 C++ 对象的 sizeof。`Destination` 可以表示多个目的节点；具有 DataBlk 字段也不代表每种消息都携带有效数据。

一次 CPU 读缺失不是把 RubyRequest 强行转换成同一个 RequestMsg 对象，而是控制器识别 Load 事件后，根据状态执行 sendGetS，另外构造 GetS 消息。本地读命中时就不需要发送 GetS。

## 5. MessageBuffer 的重要成员

| 成员 | 在源码中负责什么 |
|---|---|
| m_prio_heap | `std::vector<MsgPtr>`，配合堆算法保存正常排队的消息；front() 是下一条候选消息 |
| m_consumer | 消费者指针，例如某个控制器或网络组件；队列通过它安排唤醒 |
| m_max_size | 容量上限，0 表示不设上限；有限容量同时考虑正常队列与阻塞消息 |
| m_strict_fifo | 是否要求严格有序，对应 Python 的 ordered |
| m_msg_counter / m_last_arrival_time | 入队顺序标记、前一条消息的就绪时间，用于排序和有序约束 |
| m_stall_msg_map / m_stall_map_size | 按块地址保存已经移出正常堆的阻塞消息，并统计其占用 |
| m_deferred_msg_map | 按地址保存尚未正式入队的消息，等待调用方之后显式提交 |
| m_max_dequeue_rate / m_dequeues_this_cy | 每周期的出队限制及本轮已出队数量，0 限制表示不设上限 |
| m_time_last_time_pop / m_size_at_cycle_start 等 | 保存同一轮操作前后的容量视图，模拟出队释放空间的可见时间 |
| m_dequeue_callback | 注册的出队回调；不等于 CPU 访问完成回调 |
| m_vnet_id / m_input_link_id | 虚拟网络和输入链路相关标识 |

另外，`m_priority_rank` 与 `m_routing_priority` 用于相关优先级接口；不能把这些字段理解为 m_prio_heap 首先按“消息重要程度”排序。

## 6. enqueue：入队同时安排未来的处理机会

C++ 接口的核心参数是：

```cpp
void enqueue(MsgPtr message, Tick curTime, Tick delta,
             bool ruby_is_random, bool ruby_warmup,
             bool bypassStrictFIFO = false);
```

这里 `curTime` 和 `delta` 都按 **Tick** 表示。下面是帮助阅读的简化逻辑，不是完整可替换的源码：

```text
记录本轮入队次数，增加消息计数
检查 delta=0 是否被配置允许
计算 arrival_time：普通路径为 current_time + delta；随机化路径另算
检查严格有序约束
更新消息累计延迟、就绪时间和队内顺序标记
将消息放入 m_prio_heap，维护堆
检查有限容量不被超出，更新统计
通过 m_consumer 安排 arrival_time 对应的唤醒
```

源码中的两个关键操作是：

```cpp
msg_ptr->setLastEnqueueTime(arrival_time);
m_consumer->scheduleEventAbsolute(arrival_time);
```

因此，**enqueue 不会立即调用控制器处理消息，也不意味着消息现在就已到达接收方**。它设置“最早可用的时间”，再通过事件机制预约处理机会。

### SLICC 的 enqueue(..., 1) 为什么又说是一个周期

```slicc
enqueue(request_out, RequestMsg, 1) {
    // 填写 out_msg 的地址、类型、目的地等
}
```

SLICC 的延迟参数按控制器周期表达。EnqueueStatementAST.py 生成代码时使用 `cyclesToTicks(Cycles(...))` 转成 Tick，再调用 MessageBuffer 的 C++ enqueue。Sequencer::issueRequest 也会先通过 cyclesToTicks 转换 mandatoryQueueLatency。

所以 **“SLICC 中 1 个周期”不等于“C++ 中 1 个 Tick”**；这一段队列延迟也不等于整个网络或整个内存访问的延迟。

## 7. isReady、peek、dequeue：检查、查看和移除

| 函数 | 主要语义 | 阅读时注意 |
|---|---|---|
| isReady(current_time) | 队列非空、队头就绪时间已到，并且允许继续出队 | 非空不等于就绪；出队速率限制也可能使其返回 false |
| readyTime() | 返回队头的最早就绪时间，空队列返回 MaxTick | 不是承诺控制器届时一定能完成处理 |
| peek() / peekMsgPtr() | 查看队头消息 / 指针 | 不移除；调用方应满足相应非空、就绪前提，正常 in_port 先检查 isReady |
| dequeue(current_time) | 移除已就绪队头，更新延迟和统计，执行已注册出队回调 | 返回的是 Tick 类型累计延迟，不是 Message 指针 |
| isEmpty() | 只检查正常消息堆是否为空 | 正常堆为空时，阻塞表或延迟入队表仍可能有消息 |

无随机化、未超出出队限制时，可以这样手算：

```text
Tick 100：enqueue(A, current_time=100, delta=20, ...)
          A 的最早就绪时间为 120
Tick 110：isReady(110) 为 false，虽然正常队列里已经有 A
Tick 120：isReady(120) 可为 true
          peek() 看到 A，但 A 仍留在队列中
          dequeue(120) 才移除 A
```

即使消息已就绪，控制器仍可能因为 TBE、状态或输出空间不足无法接手。**到达、出队、整个事务完成，是三个不同的时刻。**

## 8. 堆排序、ordered=True 与容量背压

### 8.1 m_prio_heap 按什么排序

Message.hh 的 `operator>(MsgPtr, MsgPtr)` 先比较 `getLastEnqueueTime()`，相同则比较 `getMsgCounter()`。MessageBuffer 使用 `std::greater<MsgPtr>` 维护堆，使更早就绪的消息位于 front()。

因此这里的 priority heap 主要表达时间顺序，不是说 GetM 一定比 GetS 优先，也不是 gem5 EventQueue 的“时间 + 事件优先级”结构。

`ordered=True` 会启用严格 FIFO 约束。在普通无随机化路径，若新消息的 arrival_time 早于上一条且没有显式绕过条件，会触发 FIFO violation；**不是无条件自动把时间改成合法值**。随机化、有意 bypass 和重新处理路径要结合相应代码看，不能用一个布尔值推断全系统永远严格有序。

### 8.2 areNSlotsAvailable 为什么不只是比较 vector.size()

`areNSlotsAvailable(n, current_time)` 用于判断还能否接收 n 条消息：

- `m_max_size == 0` 时直接允许，表示该队列不设有限容量限制。
- 有限容量时，正常堆和 stall map 中的消息都占用资源；把消息阻塞起来不代表释放了缓冲槽位。
- 新入队立即影响可见容量；同一轮出队不会立即让发送方看见空位，需要结合周期起始快照判断。

这是背压建模的一部分，避免因同一轮函数调用顺序不同而把空间重复使用。调用方应按资源接口检查容量；enqueue 本身不是一个“空间不足就返回 false”的 try-enqueue API，容量超出会触发断言。

`getSize(curTime)` 是正常堆大小的时间点缓存视图，不等于“正常堆 + 阻塞表 + 延迟表”的全部待处理消息总量，不能替代容量检查。

## 9. 消息暂时处理不了：四种情况要区分

| 情况 | 消息在哪里 | 如何再次处理 |
|---|---|---|
| 协议 action 中的 stall | 在教学 MSI 的相应路径中不弹出当前输入消息 | 等其他输入事件或资源变化带来后续处理机会 |
| recycle(current_time, latency) | 仍在正常堆里，更新就绪时间并重新排堆 | 安排未来唤醒，届时重新检查 |
| stallMessage(addr, current_time) | 从正常堆移到 m_stall_msg_map[addr] | 接收方之后显式调用 reanalyzeMessages / reanalyzeAllMessages |
| deferEnqueueingMessage(addr, msg) | 存在 m_deferred_msg_map，尚未正式 enqueue | 调用方必须之后调用 enqueueDeferredMessages，才进入正常队列 |

`stallMessage` 内部调用 `dequeue(current_time, false)`，是移动消息，不把它当成最终离开缓冲区。源码明确说明：**这里不会自动安排重新检查阻塞表的事件**。若控制器忘记 reanalyze，不能指望时间推进后这些消息自动回来。

这里的 `false` 控制部分消息数量统计，并不跳过 dequeue 的全部其他行为：出队次数仍会更新，已注册的出队回调仍可能执行。因此，看到 dequeue 回调也不能据此认定消息已完成协议处理。

reanalyzeMessages 会把指定地址的阻塞消息放回正常堆、更新阻塞计数，并安排消费者处理。它表示“请重新尝试”，不是“现在必定满足全部协议条件”。

同样，不要将 MessageBuffer::clear 当成“清除一切未完成事务”：当前实现清理正常堆及部分计数，没有在该函数中清空 stall map 和 deferred map，更不会替控制器释放 TBE。

## 10. Consumer：怎样连回 gem5 的事件调度

Consumer 持有 `EventFunctionWrapper m_wakeup_event` 和一组待唤醒时间 `m_wakeup_ticks`。以 enqueue 为起点继续读：

1. MessageBuffer 调用 `m_consumer->scheduleEventAbsolute(arrival_time)`。
2. Consumer 将该时间向上对齐到所属对象的时钟边界，加入待唤醒集合。
3. scheduleNextWakeup 查找下一次唤醒；没有已排事件时 schedule，更早的时间到来时可 reschedule。
4. 事件触发后调用 processCurrentEvent，移除本次时间、执行虚函数 wakeup，再安排下一次唤醒。

所以 **MessageBuffer 负责就绪时间，Consumer 负责定时唤醒，控制器的 wakeup / 输入处理负责推进状态机**。消息不是被一个宿主线程 sleep 到点后再取出来的。

`setConsumer()` 设置队列消费者；重复关联会 fatal。控制器输入队列的关联可在 SLICC 的 StateMachine.py 生成逻辑中找到 `setConsumer(this)`。输出队列的消费者则可能是网络组件，并非所有 MessageBuffer 都由 L1 控制器直接消费。

## 11. 与 Sequencer、SLICC 控制器和网络串起来

以本地 CPU 冷读为例：

```text
Sequencer::issueRequest
    创建 RubyRequest，计算 mandatoryQueue 延迟（周期 → Tick）
    调用 m_mandatory_q_ptr->enqueue(...)
        ↓
MessageBuffer 安排消费者唤醒
        ↓
控制器 mandatory_in：isReady → peek RubyRequest → trigger Load
        ↓
transition(I, Load, IS_D)：分配缓存条目和 TBE，执行 sendGetS
        ↓
sendGetS 的 SLICC enqueue(request_out, RequestMsg, 1)
    生成新的 GetS 消息，放入 requestToDir
        ↓
网络消费 requestToDir，将消息传给目录
        ↓
目录处理并返回消息，本地响应队列再次唤醒本地控制器
        ↓
控制器填充缓存、释放相应 TBE、回调 Sequencer，最终回应 CPU
```

在 MSI-cache.sm 中，`popMandatoryQueue`、`popResponseQueue` 等动作调用关联队列的 dequeue。**peek / trigger 本身不等于出队，pop 也不等于整笔 CPU 请求完成。** 冷读可以先移除已经接手的 mandatoryQueue 请求，再由 TBE 跟踪等待数据的过程。

Python 中 `MessageBuffer.in_port/out_port` 用于配置连接关系；SLICC 中 `in_port/out_port` 则声明消息处理入口和消息类型。不要把这里的实际消息传输理解成普通 C++ RequestPort 直接调用 sendTimingReq；Ruby 的消息入队和网络传递遵循其自身接口。

## 12. functional 访问与调试时先看什么

数据可能正在消息中传输，尚未落入最终缓存或内存。functionalRead / functionalWrite 因而需要考虑队列内的消息，而不是只查缓存条目。

MessageBuffer::functionalAccess 遍历正常堆和 stall map，调用具体消息的 functional 方法；当前实现没有在这个函数里遍历 deferred map。教学 MSI 中，ResponseMsg 的无掩码 functionalRead 仅在类型为 Data 时尝试读数据，RequestMsg 的对应方法直接返回 false。不能因为类型都有 DataBlk 就假定它们的可读语义相同。

遇到“消息明明发了，控制器却没处理”时，按顺序核对：

1. 是否真正 enqueue，进入哪个 MessageBuffer，而非仅创建了消息对象？
2. arrival_time 是多少，当前 tick 是否已到，是否做了周期/Tick 转换？
3. consumer 是否关联，唤醒时间是否对齐并排入事件队列？
4. isReady 是否被出队速率限制，或消息实际上已在 stall / deferred 表里？
5. 控制器是否受到状态、TBE 或输出空间限制，是否执行了 pop、recycle 或 reanalyze？
6. 出队后是否只是进入了新的网络阶段，而不是事务已经完成？

相关函数使用 `RubyQueue` 调试标志，可先用实际二进制的 `--debug-help` 核对，再针对短仿真、地址和时间窗收集日志。源码中的 `m_dequeue_callback` 只是队列出队通知；CPU 完成仍应继续追控制器对 Sequencer 的回调。

## 13. 建议阅读顺序与自检

第一轮：Message.hh → MessageBuffer.hh → enqueue → isReady → peek/dequeue → Consumer.cc。

第二轮：Sequencer::issueRequest → MSI-cache.sm 的 mandatory_in / sendGetS / pop 动作 → MSI-msg.sm → 对端目录输入处理。

第三轮：areNSlotsAvailable → stall/recycle/reanalyze/deferred → functionalAccess → 对应 SLICC 代码生成位置。

读完应能解释：

- 消息已入队，为什么仍然不能处理？
- 为什么 peek 后还需要 pop？为什么 dequeue 返回 Tick 而不是消息？
- 为什么出队释放的空间不一定立即对发送方可见？
- 什么情况下按地址阻塞，谁负责恢复？
- 为什么队列的出队通知不是 CPU 请求完成？

掌握这些后，再看 SimpleNetwork 或 Garnet，就能区分“协议队列等待”“控制器资源阻塞”和“网络传输/拥塞”等不同延迟来源。
