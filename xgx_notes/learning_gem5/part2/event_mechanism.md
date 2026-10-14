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
