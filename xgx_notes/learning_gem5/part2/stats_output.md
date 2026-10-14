# Part 2 · 第 4 章：事件、调试输出与退出机制（HelloObject / GoodbyeObject）

> 对应源码：`src/learning_gem5/part2/hello_object.{hh,cc}` + `goodbye_object.{hh,cc}` + `HelloObject.py`
> 配置脚本：`configs/learning_gem5/part2/hello_goodbye.py`

> 原理专题：[gem5 事件机制：时间推进、调度器与队列顺序](event_mechanism.md)。建议先结合本章示例理解事件，再追踪调度器源码。

## 本章目标

理解 gem5 的**事件驱动(event-driven)**模型、**调试标志(debug flag)**，以及
**如何主动结束模拟(exitSimLoop)**。对应书中「统计与输出」一章。

## 关键概念 1：事件（Event）

gem5 是事件驱动的：所有动作都通过「在某个 tick 调度一个函数」来实现。
用 `EventFunctionWrapper` 把 C++ lambda 包装成事件：

```cpp
// HelloObject 构造时创建事件（触发时调用 processEvent()）
event([this]{ processEvent(); }, name() + ".event")

// startup() 里调度第一次触发
schedule(event, latency);

// processEvent() 里决定是再次调度还是收尾
schedule(event, curTick() + latency);   // 继续
```

## 关键概念 2：调试标志（DebugFlag + DPRINTF）

- 在 `SConscript` 里注册：`DebugFlag('HelloExample', "…")`。
- C++ 里用 `DPRINTF(HelloExample, "…")` 打印调试信息。
- 运行时加 `--debug-flags=HelloExample` 才显示（否则静默）：

```bash
build/X86/gem5.opt --debug-flags=HelloExample configs/learning_gem5/part2/hello_goodbye.py
```

## 关键概念 3：主动结束模拟

`GoodbyeObject` 的缓冲区填满后，调用 `exitSimLoop` 结束模拟：

```cpp
exitSimLoop(buffer, 0, curTick() + bandwidth * bytes_copied);
```

第一个参数会变成 `simulate()` 的退出原因（cause），也就是脚本里打印的
`exit_event.getCause()`。

## 两个 SimObject 的协作

```python
# hello_goodbye.py
root.hello = HelloObject(time_to_wait="2us", number_of_fires=5)
root.hello.goodbye_object = GoodbyeObject(buffer_size="100B")
```

- `HelloObject`：每隔 `2us` 触发一次事件，共 5 次；第 5 次后调用 `goodbye->sayGoodbye()`。
- `GoodbyeObject`：以 `100MiB/s` 的带宽往 `100B` 缓冲区里填 "Goodbye hello!! …"，
  填满就 `exitSimLoop`。

## 运行

```bash
# 在仓库根目录执行
build/X86/gem5.opt configs/learning_gem5/part2/hello_goodbye.py
```

## 实际输出

```
Beginning simulation!
Exiting @ tick 10944163 because Goodbye hello!! Goodbye hello!! Goo…
```

**要点**：
1. 退出原因（cause）就是 GoodbyeObject 填进缓冲区的那段字符串——直接印证了
   `exitSimLoop` 第一个参数会成为 cause。
2. 加上 `--debug-flags=HelloExample` 再跑，能看到每个事件触发时的 `DPRINTF` 输出，
   直观看到事件的调度与触发过程。
3. 每次跑完 `m5out/` 下会生成 `stats.txt` / `config.ini` / `config.json`，这是理解
   模拟系统行为的主要输出文件。

## 分步实验 C2：用时间戳证明事件调度

**重点逻辑：事件在未来时间点调用回调；回调可以继续调度事件，也可以通知另一个对象。最终退出是被模型明确安排的动作。**

### 步骤 1：运行带调试的基线

```bash
build/X86/gem5.opt --outdir=m5out/learning/c2_base --debug-flags=HelloExample --debug-file=events.log configs/learning_gem5/part2/hello_goodbye.py
rg -n 'Processing|Done firing|Saying goodbye|Scheduling|done copying' m5out/learning/c2_base/events.log
```

把 Hello 的五次 `Processing the event` 单独抄成时间表。不要把 Goodbye 的同类日志误计为 Hello 触发次数。对照 `startup()` 和 `processEvent()`，确认第一次调度时间和后续相邻事件的间隔。

### 步骤 2：只改变事件次数

复制配置为同目录 `hello_goodbye_lab.py`。保持 `time_to_wait="2us"` 与 Goodbye 参数不变，把 `number_of_fires=5` 改为 `3`，输出到 `c2_count3`。预期 Hello 触发三次，Goodbye 比基线早开始约 4us；不要要求退出 tick 匹配笔记中的历史数字。

### 步骤 3：只改变事件间隔

从基线参数出发，保持五次触发，把 `time_to_wait` 改为 `"1us"`，输出到 `c2_interval1`。预期 Hello 最后一次触发提前约 5us；Goodbye 的填充耗时应保持不变。用日志分别验证“前半段等待”与“后半段填充”，避免只看总时间。

### 步骤 4：分析带宽模型

保持 Hello 不变，给 Goodbye 显式设置 `write_bandwidth="50MiB/s"`，比较基线的 `100MiB/s`。阅读 `fillBuffer()`：每轮复制一段消息，再按 `bandwidth * bytes_copied` 调度下一动作；缓冲保留结尾字符位置，时间换算也可能取整。

预期填充阶段变长，总时间不会简单翻倍。这里 C++ 的 `bandwidth` 使用转换后的时间/字节表示，需要根据参数转换与日志理解，不能按变量名猜量纲。

**验收**：三组单变量结果、Hello 时间表、最后触发/Goodbye 开始/退出的时间线，并解释 `schedule(event, tick)` 的 tick 是绝对时间，而常用 `curTick() + latency` 表达相对等待。
