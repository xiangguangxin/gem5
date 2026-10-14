# gem5 事件机制：从 HelloObject 到事件队列

> 推荐在 SimpleObject 之后阅读，与[事件与调试实验](stats_output.md)配合。本文依据当前仓库源码，首先讨论单个事件队列的常规调度；多线程、多队列需要另外考虑同步规则。

## 1. 什么是事件

事件（Event）表达“在某个仿真时间点，执行一项模型动作”。例如 CPU 下一次执行、缓存查询完成、内存响应返回或 DMA 完成。

```text
事件 = 触发时间 + 优先级 + 要执行的动作
```

不是每个普通函数调用都需要独立事件；同一个事件回调可以直接完成多项动作。模型需要表达未来动作时，才安排相应事件。

## 2. 仿真时间怎样推进

`m5.simulate()` 进入事件处理循环，队列选出下一个待执行事件，调度器把当前仿真时间更新到事件时间，然后执行其回调。

```text
当前 0ns
  → 取出 10ns 的事件，推进到 10ns，执行动作
  → 取出 30ns 的事件，推进到 30ns，执行动作
  → 取出 100ns 的事件，推进到 100ns，执行动作
```

没有事件的区间不需要逐 tick 遍历。模型也不应通过宿主机 `sleep()` 表达硬件延迟。

| 概念 | 含义 |
|---|---|
| tick | 仿真时间单位 |
| CPU cycle | CPU 时钟周期，长度由时钟配置决定 |
| 宿主机时间 | 运行 gem5 实际花费的时间 |

当日志报告每秒 `1000000000000` tick 时，1 tick = 1ps，2000000 tick = 2us。这不是 CPU 的频率，也不能假定所有配置都使用该 tick 频率。

## 3. event 与 schedule 如何配合

在 `hello_object.hh` 中：

```cpp
EventFunctionWrapper event;
```

它声明一个事件成员。构造函数初始化列表中：

```cpp
event([this]{ processEvent(); }, name() + ".event")
```

- `[this]{ processEvent(); }` 是 lambda，捕获当前对象指针，以便调用其成员函数。
- `name() + ".event"` 为事件提供名字。
- 初始化只绑定回调，不会立即执行 `processEvent()`。

`EventFunctionWrapper` 的 `process()` 会调用保存的函数，定义见 [eventq.hh](../../../src/sim/eventq.hh)。

接着安排执行时间：

```cpp
schedule(event, curTick() + latency);
```

`curTick()` 为当前仿真时间，`latency` 在这个示例中已经转换为 tick。`schedule` 的时间参数是**绝对时间**，不是相对延迟：

```text
当前 2us + latency 2us → 在 4us 触发 event
    → wrapper 执行 lambda
    → lambda 调用 HelloObject::processEvent()
```

**event 决定做什么，schedule 决定何时做，事件调度器负责到时执行。**

## 4. HelloObject 的完整事件链

源码入口：[HelloObject.py](../../../src/learning_gem5/part2/HelloObject.py)、[hello_object.hh](../../../src/learning_gem5/part2/hello_object.hh)、[hello_object.cc](../../../src/learning_gem5/part2/hello_object.cc)。

Python 配置：

```python
root.hello = HelloObject(time_to_wait="2us", number_of_fires=5)
```

C++ 初始化参数：

```cpp
latency(params.time_to_wait),
timesLeft(params.number_of_fires)
```

`number_of_fires` 是配置的总次数；`timesLeft` 是运行中不断减少的剩余次数。

### 首次调度

```cpp
void HelloObject::startup()
{
    schedule(event, latency);
}
```

在本示例从 tick 0 开始的情况下，首次触发在 2us。这里直接使用 `latency` 是将它作为绝对时间；不能把这种写法无条件搬到非零时间起点的代码里。

### 触发、递减和再次调度

```cpp
void HelloObject::processEvent()
{
    timesLeft--;
    DPRINTF(HelloExample, "Hello world! Processing the event! %d left\n",
            timesLeft);
    if (timesLeft <= 0) {
        DPRINTF(HelloExample, "Done firing!\n");
        goodbye->sayGoodbye(myName);
    } else {
        schedule(event, curTick() + latency);
    }
}
```

| 时间 | 减一后的 timesLeft | 动作 |
|---|---|---|
| 2us | 4 | 安排 4us 的事件 |
| 4us | 3 | 安排 6us 的事件 |
| 6us | 2 | 安排 8us 的事件 |
| 8us | 1 | 安排 10us 的事件 |
| 10us | 0 | 调用 Goodbye，不再调度 Hello |

这不是在回调内循环等待五次；每次回调只处理当前一次，再返回调度器。这里的 `goodbye->sayGoodbye(myName)` 是直接方法调用，本身不是另一个事件；Goodbye 内部再决定是否安排后续填充事件。

## 5. 调度器在哪里

沿这条调用链阅读，不必一开始通读全部实现：

```text
Python m5.simulate()                 src/python/m5/simulate.py
    → Python/C++ 绑定                src/python/pybind11/event.cc
    → C++ simulate()                 src/sim/simulate.cc
    → doSimLoop(eventq)              src/sim/simulate.cc
    → EventQueue::serviceOne()       src/sim/eventq.cc
    → event->process()
    → wrapper 回调
    → HelloObject::processEvent()
```

[serviceOne()](../../../src/sim/eventq.cc) 中最关键的两句是：

```cpp
setCurTick(event->when());
event->process();
```

它在取出事件后更新时间并执行动作；执行前还清除了该事件的 Scheduled 标志，所以回调可以重新调度同一个成员事件。

“仿真调度器”是这些管理和执行机制的统称，不是名为 Scheduler 的单独类。

## 6. EventQueue 是 list 吗

主队列采用**事件内嵌指针构成的两层链表**，不是直接用 `std::list` 存储所有待执行事件。

```cpp
// EventQueue
Event *head;

// Event
Event *nextBin;
Event *nextInBin;
```

- `nextBin` 连接不同的 bin；一个 bin 对应相同触发时间与优先级。
- `nextInBin` 连接同一个 bin 中的事件，采用栈式组织。

```text
head
 ↓
[10ns, priority 0] ──nextBin──→ [10ns, priority 10] ──→ [20ns, priority 0]
 ↓ nextInBin
[10ns, priority 0]
 ↓
[10ns, priority 0]
```

时间越早越先处理；同一时间优先级数值越小越先处理，比较逻辑见 `eventq.hh` 的 `operator<`。

另外有一个 `std::list<Event*> async_queue`，用于接收其他线程提交的事件，随后合并进主队列。不要将这个辅助队列与主事件队列混淆。

## 7. 同时间、同优先级：为什么是 LIFO

当前源码明确将同 bin 的事件组织为栈。`Event::insertBefore()` 在同组情况下执行：

```cpp
event->nextInBin = curr;
```

因此依次调度 A、B、C 且它们时间、优先级完全相同时：

```text
插入 A：A
插入 B：B → A
插入 C：C → B → A
执行：  C → B → A
```

这些回调串行执行，仿真时间保持不变，并不是同时运行。如果 C 又调度当前时间、同优先级的 D，且没有退出等特殊动作打断，顺序会变成 C → D → B → A。

### 为什么不用 FIFO

源码注释强调分组链表与组内栈的操作开销优势。组内头插不需要遍历尾部，也无需维护尾指针；普通取组头也是常数时间。任意移除仍应结合具体实现分析，不能推断所有队列操作都是 O(1)。

FIFO 同样可以通过尾指针实现 O(1) 插入，因此不能说“只有 LIFO 高效”，也不能仅凭实现断言作者的全部设计动机。主队列跨 bin 的插入还需要寻找位置。

**LIFO 是同组事件打破平局的实现规则，不代表真实硬件天然后进先出。** 有依赖关系时，优先让 A 完成后再启动 B；确实属于不同执行阶段时，可按模型约定设计优先级。不要仅靠隐含插入顺序表达硬件依赖。

## 8. 调度时的约束

在 `EventQueue::schedule()` 中可看到以下检查：

```cpp
assert(when >= getCurTick());
assert(!event->scheduled());
assert(event->initialized());
```

因此应注意：

- 不调度到过去；同一 tick 可以调度事件，但无限零延迟重调度会让时间无法前进。
- 已在队列里的同一个事件不能直接再次 schedule；根据需要使用 `scheduled()`、`deschedule()` 或 `reschedule()`，并核对相关 API 语义。
- `[this]` 捕获的是指针，不会自动延长对象寿命；回调执行前对象必须仍然有效。
- 本文的链表/LIFO解释针对单个队列；多队列并行不是简单把它推广成全局顺序。

## 9. 通过日志观察事件驱动

在仓库根目录运行：

```bash
build/X86/gem5.opt --outdir=m5out/learning/c2_base \
  --debug-flags=HelloExample --debug-file=events.log \
  configs/learning_gem5/part2/hello_goodbye.py
rg 'hello:.*Processing the event' m5out/learning/c2_base/events.log
```

默认参数下，Hello 日志应对应 2/4/6/8/10us，剩余次数是 4/3/2/1/0。Goodbye 也有事件日志，统计 Hello 触发次数时要区分对象名。

未启用调试标志时，终端只看到开始与退出，不意味着内部没有事件。

例如退出于 `10944163 tick`，在每秒 10¹² tick 的配置下约为 10.944163us。退出原因中重复的 `Goodbye hello!!` 来自 Goodbye 的缓冲内容；末尾不完整是容量截断，不是错误。具体时间以实际模型参数与实现为准。

SimpleObject 示例没有业务事件，但 `simulate()` 会安排仿真时间上限退出事件；达到最大 tick 不表示实际经过了相应宿主机时间。

## 10. 练习：用修改验证理解

1. 按[实验 C2](stats_output.md)把 Hello 次数从 5 改为 3，预测并核对最后触发时间。
2. 保持次数不变，将间隔改为 1us，逐条对照 schedule 与日志。
3. 进阶：在练习对象中声明三个独立 `EventFunctionWrapper`，回调分别打印 A/B/C。在 startup 中按 A/B/C 顺序调度到同一未来 tick，保持相同默认优先级；重新编译后验证 C/B/A 顺序。
4. 再改变一个事件的优先级，依据当前构造函数签名设置参数，预测同 tick 的先后顺序。不要同时改变时间与优先级。

**验收**：能画出“绑定回调 → schedule → 入队 → 更新时间 → process → 再次调度”的完整路径；能解释 tick、优先级、LIFO 与业务因果关系的区别。

## 11. 异步请求：外部怎样控制正在运行的仿真

### async_event 是总提醒标志

[async.hh](../../../src/sim/async.hh) 声明了这些全局变量，[async.cc](../../../src/sim/async.cc) 给出初始值：

```cpp
extern volatile bool async_event;
extern volatile bool async_exit;
extern volatile bool async_statdump;
extern volatile bool async_statreset;
extern volatile bool async_io;
extern volatile bool async_exception;
```

`async_event` 是布尔标志，不是 Event 对象，也不是其他标志的父对象。它提醒主循环“有外部请求需要检查”；独立的具体标志说明要做什么，多个请求可以同时置位。

| 标志 | 主循环中的处理 |
|---|---|
| async_exit | 调用 exitSimLoop，安排退出 |
| async_statdump | 安排统计输出事件 |
| async_statreset | 安排统计重置事件 |
| async_io | 调用 pollQueue.service，服务宿主机 I/O |
| async_exception | 清除标志并返回空指针 |

当前标准循环还处理 `async_hypercall`，具体以 [simulate.cc](../../../src/sim/simulate.cc) 为准。

例如，外部信号处理程序设置退出请求：

```text
外部请求 → async_exit=true，async_event=true
    → 主循环在事件之间检查
    → 清除对应标志，调用 exitSimLoop()
    → 队列处理退出事件
    → 返回调用者
```

外部信号处理入口可看 [init_signals.cc](../../../src/sim/init_signals.cc)。主要操作推迟到仿真循环处理，而不是在信号处理函数里直接执行复杂仿真逻辑。`volatile` 不等于原子变量或线程锁，不能据此推断任意跨线程读写都是安全的。

### 与正常模型事件的区别

| 机制 | 含义 |
|---|---|
| schedule(event, tick) | 按仿真时间安排模型动作 |
| async_event 等标志 | 外部在宿主机侧提出控制/服务请求 |
| async_queue | 其他线程向某个事件队列提交事件的辅助容器 |

CPU 异步访存、DMA 请求属于模型交互，不等于 `async_event` 外部控制路径。正常事件也不必一概叫“同步事件”。

### doSimLoop 的处理顺序

标准循环的核心结构可以概括为：

```cpp
while (true) {
    // 检查队列非空，下一事件不在过去
    if (mainQueue && async_event) {
        async_event = false;
        // 持有队列锁，检查并处理各具体请求
    }
    Event *exit_event = eventq->serviceOne();
    if (exit_event != nullptr)
        return exit_event;
}
```

这不是完整源码，而是用于理解顺序的摘录。“先处理异步请求”可能只是把请求转换成统计/退出事件，最终动作仍由队列执行。普通调用 `exitSimLoop()` 或输出统计，也不一定经过异步标志路径。

嵌入组件的 `doSimLoop()` 可能是删去同步屏障的变体。对照时检查总标志是否清除、锁是否实际获取、是否处理所有需要的请求；注释说“加锁”不代表代码已经加锁。

## 12. serviceOne：出队、推进时间、执行与返回

源码位于 [eventq.cc](../../../src/sim/eventq.cc) 的 `EventQueue::serviceOne()`。它处理一个队头事件，调用方负责保证队列非空。

### 第一步：锁住队列并记住当前事件

```cpp
std::lock_guard<EventQueue> lock(*this);
Event *event = head;
Event *next = head->nextInBin;
event->flags.clear(Event::Scheduled);
```

`lock_guard` 在作用域结束时自动解锁，包括提前 return。`event` 保存本次事件，`next` 是同 bin 的后继，而不是下一时间组。

Scheduled 表示“当前在队列等待”，取出事件就清除。正在执行不是等待执行，因此回调能够安排该事件的下一次触发。

### 第二步：维护两层链表

```cpp
if (next) {
    next->nextBin = head->nextBin;
    head = next;
} else {
    head = head->nextBin;
}
```

同组还有事件时，新组头接管旧组头的 nextBin。这个更新必要，因为只有组头的跨组连接保证有效。组内没有剩余事件时，直接切到下一组。

```text
原来：head → A ──nextBin──→ 下一组
             ↓ nextInBin
             B

取出 A：head → B ──nextBin──→ 下一组
```

事件先从链表移除，之后才执行回调，避免一边作为待执行节点、一边重新入队。

### 第三步：跳过作废事件，执行有效事件

```cpp
if (!event->squashed()) {
    setCurTick(event->when());
    if (debug::Event)
        event->trace("executed");
    event->process();
    // 随后判断是否为退出事件
} else {
    event->flags.clear(Event::Squashed);
}
```

未作废时才更新时间并执行虚函数 `process()`。`EventFunctionWrapper::process()` 再调用保存的函数，所以最终进入业务回调。

`debug::Event` 只控制跟踪日志，不控制动作是否执行。已作废的事件跳过回调，也不会通过这里的 `setCurTick()` 推进时间。

### 第四步：识别退出事件

```cpp
if (event->isExitEvent()) {
    assert(!event->flags.isSet(Event::Managed) ||
           !event->flags.isSet(Event::IsMainQueue));
    return event;
}
```

这段位于有效事件的 `process()` 之后。断言禁止同时具有 Managed 与 IsMainQueue 标志的组合；它不是退出条件本身。返回事件让外层 doSimLoop 结束本次循环，不一定直接结束整个 gem5 进程，调用方可以继续处理或再次运行仿真。

退出路径直接返回，不执行下面普通路径的 release；其生命周期应结合退出事件及调用方处理理解。

### 第五步：普通事件释放与返回

```cpp
event->release();
return NULL;
```

普通事件或被跳过的事件走到这里，返回空指针表示“本次没有返回退出事件”，外层通常继续处理队列。

但 `async_exception` 也可能让 doSimLoop 返回空指针，不能把不同函数返回的 NULL 混成同一种含义。

## 13. Scheduled 与 Squashed：位置状态和有效性状态

### flags 是位集合

```cpp
static const FlagsType Squashed = 0x0001;
```

这里定义的是 Squashed 位的掩码。具体事件是否作废取决于其 `flags` 中该位是否置位，不是这个常量本身变化。

```cpp
event->squash();                       // 设置 Squashed 位
// serviceOne 内部会检查 event->squashed()
```

### 两个标志可以同时成立

| Scheduled | Squashed | 含义 |
|---|---|---|
| false | false | 当前不在队列，例如新事件或已经出队的事件 |
| true | false | 在队列中，动作有效 |
| true | true | 在队列中，但到时应跳过动作 |

Scheduled=false 不表示对象已销毁，也不表示不会再次调度。Squashed 是动作有效性标志，不是“已从队列删除”。

```text
schedule：Scheduled=true
    → squash：Squashed=true，仍留在队列
    → serviceOne 出队：Scheduled=false
    → 发现作废：不执行动作，清除 Squashed
    → release
```

### 为什么出队先清除 Scheduled

`schedule()` 检查 `!event->scheduled()`，防止同一事件对象重复入队。Hello 回调中重新 schedule 是合法的，因为 serviceOne 已将当前这次出队并清除标志。

```text
等待本次执行：Scheduled=true
    → 取出并开始执行：Scheduled=false
    → 回调安排下次：Scheduled=true
```

一个对象可以反复触发，但同一个事件对象不能同时表示队列中的多个节点；需要多个独立的未完成动作时，应设计独立事件或工作队列。

## 14. schedule、squash、deschedule、reschedule 怎样选

| 操作 | 是否立即移出主队列 | 用途与约束 |
|---|---|---|
| schedule | 不适用，插入队列 | 新安排未调度事件，不能在过去 |
| squash | 否 | 标记已有动作作废，到出队时跳过 |
| deschedule | 是 | 撤销当前已调度事件，并调用 release |
| reschedule | 先移出再插入 | 修改已调度事件的时间；当前实现会清除 Squashed |

`reschedule(..., always=false)` 默认要求事件已经调度；允许从未调度状态安排时需显式 `always=true`，并满足时间、初始化和队列归属检查。参考 [eventq.hh](../../../src/sim/eventq.hh) 的实际实现。

对普通、非自动删除的成员事件，可以按意图选择：

```cpp
// 取消待执行动作
if (event.scheduled())
    deschedule(event);

// 确保未来有一次触发，已有则修改时间
if (event.scheduled())
    reschedule(event, curTick() + latency);
else
    schedule(event, curTick() + latency);
```

这两个片段是不同用例，不要机械地连续执行。对于生命周期受管理的动态事件，deschedule 可能释放对象，之后不能继续使用旧指针。

## 15. release 不等于无条件 delete

[Event::release()](../../../src/sim/eventq.cc) 只有在 Managed 标志启用时才调用生命周期钩子 `releaseImpl()`。默认实现检查事件是否仍已调度，未调度时才删除；子类可以覆盖钩子。

因此：

- HelloObject 的普通成员事件不会因为每次执行就被 delete。
- 回调重新调度自身后，release 不能简单把它当作彻底结束的动作删除。
- 动态事件使用 Managed/AutoDelete 时，需要遵守相应所有权规则。
- 捕获 this 不管理模型寿命，模型销毁前必须妥善处理未完成事件。

**事件的队列状态、动作是否有效、对象是否存活，是三个不同问题。** 不能用一个 Scheduled 或 Squashed 标志回答全部问题。

## 16. 管理行为验证练习

在独立练习对象或练习副本中完成，保留 HelloObject 基线；C++ 变更后重新编译。

| 实验 | 操作 | 预期证据 |
|---|---|---|
| 重新调度 | 回调打印 scheduled 状态，再 schedule 自己 | 入回调时为 false，重新入队后为 true |
| squash | startup 中调度 A 到 2us、B 到 4us，并将 A squash | A 回调不打印，B 正常执行 |
| deschedule | 调度成员事件 A，再撤销它 | A 从队列移除，无回调 |
| reschedule | 将 A 从 2us 改到 6us | 只在 6us 触发一次 |
| 同组顺序 | 同 tick、同优先级按 A/B/C 插入 | 回调按 C/B/A 执行 |

事件日志可在 HelloExample 的基础上增加通用 Event 跟踪：

```bash
build/X86/gem5.opt --outdir=m5out/learning/event_management \
  --debug-flags=HelloExample,Event --debug-file=events.log \
  configs/learning_gem5/part2/hello_goodbye.py
```

此命令验证已有 Hello 示例；上表的取消/改期等场景需要自行实现练习对象，不能期待原示例自动覆盖。让练习最后有明确的退出事件，避免只看到最大 tick。

验收时分别回答：事件是否还在队列？回调是否有效？时间是否推进？事件对象是否仍存活？逐项给出日志或源码依据，而不是只看最终退出时间。
