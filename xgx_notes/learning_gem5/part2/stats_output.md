# Part 2 · 第 4 章：事件、调试输出与退出机制（HelloObject / GoodbyeObject）

> 对应源码：`src/learning_gem5/part2/hello_object.{hh,cc}` + `goodbye_object.{hh,cc}` + `HelloObject.py`
> 配置脚本：`configs/learning_gem5/part2/hello_goodbye.py`

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
cd /home/guangxinxiang.linux/github/gem5
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
