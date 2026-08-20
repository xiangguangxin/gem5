# gem5 调试技巧笔记

> 目标：整理调试 gem5 时最常用、最实用的办法。重点包括 Debug flags、GDB、
> Ruby/SLICC 状态机、日志、统计信息、崩溃排查和性能问题定位。

## 1. 先确认自己在跑哪个 gem5

gem5 经常会有多个 build 版本，比如：

```bash
build/X86/gem5.opt
build/X86/gem5.debug
build/X86/gem5.fast
build/RISCV/gem5.opt
```

几个版本的区别：

| 版本 | 用途 |
|------|------|
| `gem5.fast` | 跑得最快，调试信息少 |
| `gem5.opt` | 常用版本，有优化，也能开 debug flag |
| `gem5.debug` | 最适合 GDB 调试，带断言和调试符号，运行慢 |

一般流程：

```bash
scons build/X86/gem5.opt -j$(nproc)
scons build/X86/gem5.debug -j$(nproc)
```

如果只是看 Ruby 状态机日志，通常 `gem5.opt` 就够了；如果要用 GDB 断点调 C++，
优先用 `gem5.debug`。

## 2. 最重要的工具：Debug flags

gem5 内部有大量 `DPRINTF()` 调试输出，运行时通过 `--debug-flags` 打开。

查看所有 debug flags：

```bash
build/X86/gem5.opt --debug-help
```

常见命令：

```bash
build/X86/gem5.opt \
  --debug-flags=RubyCache,RubyNetwork,RubySlicc \
  configs/example/se.py ...
```

把日志写入文件：

```bash
build/X86/gem5.opt \
  --debug-flags=RubyCache,RubyNetwork,RubySlicc \
  --debug-file=ruby_debug.log \
  configs/example/se.py ...
```

限制 debug 输出的 tick 范围：

```bash
build/X86/gem5.opt \
  --debug-start=1000000 \
  --debug-end=2000000 \
  --debug-flags=RubySlicc \
  configs/example/se.py ...
```

这样可以避免日志一下子爆炸。

## 3. Ruby / SLICC 常用 Debug flags

调 Ruby 协议时常用这些：

| flag | 用途 |
|------|------|
| `RubySlicc` | SLICC 状态机动作、状态转移相关输出 |
| `RubyCache` | Ruby cache controller 相关信息 |
| `RubyNetwork` | Ruby 网络消息流动 |
| `RubyQueue` | MessageBuffer / 队列相关行为 |
| `ProtocolTrace` | 协议级 trace，适合看请求流 |
| `RubyStats` | Ruby 统计相关 |

可以组合使用：

```bash
--debug-flags=RubySlicc,ProtocolTrace,RubyQueue
```

如果日志太多，先只开一个：

```bash
--debug-flags=ProtocolTrace
```

## 4. 看 Ruby 协议时的推荐排查顺序

调 Ruby/SLICC 时，不要一上来就看所有 C++ 生成代码。建议按这个顺序：

1. 看配置脚本，确认使用哪个协议和多少个 controller。
2. 看 `.slicc` 文件，确认 include 了哪些 `.sm`。
3. 看 `*-msg.sm`，确认消息类型和字段。
4. 看 `*-cache.sm`，确认 cache 侧什么时候发请求。
5. 看 `*-dir.sm`，确认 directory 侧怎么处理请求。
6. 开 `ProtocolTrace` 或 `RubySlicc`，对照状态机 transition 看日志。

比如 `MI_example`：

```text
src/mem/ruby/protocol/MI_example-msg.sm
src/mem/ruby/protocol/MI_example-cache.sm
src/mem/ruby/protocol/MI_example-dir.sm
src/mem/ruby/protocol/MI_example-dma.sm
```

## 5. 怎么读 SLICC 状态机日志

SLICC 的核心是：

```text
当前状态 + 事件 -> 动作 + 下一个状态
```

例如：

```slicc
transition(I, GETX, IM) {
    i_popIncomingRequestQueue;
    a_sendWriteBackAck;
}
```

调试时要回答几个问题：

- 当前 block 地址是什么？
- 当前 controller 是谁？L1Cache 还是 Directory？
- 当前状态是什么？
- 收到的 event 是什么？
- 执行了哪些 action？
- 最后转到了哪个状态？
- 有没有 stall / recycle？

如果看到：

```slicc
z_recycleRequestQueue;
```

通常表示当前状态不能处理这个请求，请求被放回队列，之后再试。

## 6. MessageBuffer 调试思路

Ruby 里 controller 之间靠 `MessageBuffer` 通信。

常见问题：

| 现象 | 可能原因 |
|------|----------|
| 请求发出后没响应 | 目的地 `Destination` 错了，或者对端没有处理对应 event |
| 模拟卡住 | 某个 buffer 堵住，或者某个 transient state 一直等不到消息 |
| 响应乱序 | vnet / message type / priority 设置不合理 |
| deadlock panic | 消息循环依赖、队列满、协议没有释放资源 |

排查办法：

```bash
--debug-flags=RubyQueue,RubyNetwork,ProtocolTrace
```

重点看：

- 消息有没有 enqueue
- 消息有没有 dequeue
- 发往哪个 `MachineID`
- 走哪个 virtual network
- 是否被 stall 或 recycle

## 7. 用 GDB 调试 gem5

先编译 debug 版本：

```bash
scons build/X86/gem5.debug -j$(nproc)
```

启动 GDB：

```bash
gdb --args build/X86/gem5.debug configs/example/se.py ...
```

常用 GDB 命令：

```gdb
run
bt
frame 3
list
print variable_name
break SomeClass::someFunction
continue
next
step
```

如果 gem5 panic / fatal / assert：

```gdb
run
bt
```

第一步先看 backtrace，找最早进入 gem5 自己代码的位置。

## 8. 给 C++ 加 DPRINTF

如果已有 debug flag 不够，可以在 C++ 里加：

```cpp
DPRINTF(RubyCache, "addr=%#x state=%s\n", addr, state);
```

注意需要 include 对应 debug 头文件，比如：

```cpp
#include "debug/RubyCache.hh"
```

如果要新增一个 debug flag，需要改：

```text
src/base/debug/SConscript
```

增加类似：

```python
DebugFlag('MyDebugFlag')
```

然后重新编译。

## 9. 给 SLICC 加调试输出

在 `.sm` 文件里常见方式：

```slicc
APPEND_TRANSITION_COMMENT("some message");
```

或者使用已有的 `DPRINTF` 风格输出，具体要看当前 `.sm` 文件中已有写法。

对 SLICC 状态机，最推荐先找：

```text
transition(...)
action(...)
in_port(...)
```

再把输出加在关键 action 里。

## 10. 使用 stats.txt 辅助定位

gem5 默认会在输出目录生成：

```text
m5out/stats.txt
m5out/config.ini
m5out/config.json
```

常用查看：

```bash
less m5out/stats.txt
less m5out/config.ini
```

调 Ruby 时可以搜：

```bash
grep -i ruby m5out/stats.txt
grep -i miss m5out/stats.txt
grep -i deadlock m5out/stats.txt
```

`config.ini` 很重要，可以确认实际创建了哪些对象，比如：

- L1 cache controller 数量
- Directory controller 数量
- Ruby network 类型
- MessageBuffer 连接关系
- memory range

## 11. 使用不同输出目录

不要所有实验都写到默认 `m5out`，容易覆盖。

推荐：

```bash
build/X86/gem5.opt \
  --outdir=m5out/mi_test_01 \
  configs/example/se.py ...
```

这样每次实验的：

```text
stats.txt
config.ini
config.json
debug log
```

都能保留下来。

## 12. 排查 Ruby deadlock

Ruby 协议出错时常见报错是 deadlock。

排查顺序：

1. 找 deadlock 前最后一个地址。
2. 用 `ProtocolTrace` 看这个地址的消息流。
3. 找有没有 controller 停在 transient state。
4. 检查是否少发了 response / ack。
5. 检查是否忘记 pop input queue。
6. 检查 TBE 是否忘记 deallocate。
7. 检查 MessageBuffer 的 vnet 是否匹配。

SLICC 里尤其注意：

```slicc
pop(...)
recycle(...)
stall_and_wait(...)
wakeUpBuffers(...)
```

很多卡死问题不是状态转移本身错，而是队列没有正确释放。

## 13. 排查 panic / fatal / assert

gem5 报错通常有三类：

```text
panic(...)
fatal(...)
assert(...)
```

处理方式：

1. 看终端最后 30 行。
2. 看报错文件和行号。
3. 用 `rg` 搜报错字符串。
4. 用 `gem5.debug + gdb` 复现。
5. 看 backtrace。

常用搜索：

```bash
rg "panic\\(|fatal\\(|assert\\(" src/mem/ruby
```

如果是 SLICC 生成代码报错，不要只看 `build/.../mem/ruby/protocol/...cc`，
还要回到对应 `.sm` 文件找原始状态机逻辑。

## 14. 小测试优先

调协议时尽量先跑最小 workload：

- 单核
- 小内存
- 简单 binary
- 短 tick
- 单个 benchmark region

原因很简单：协议日志会非常大。先用最小 case 复现 bug，才能看清楚消息顺序。

可以用：

```bash
--abs-max-tick=1000000
```

或者在脚本里控制 exit 条件。

## 15. 常用源码搜索技巧

找某个类：

```bash
rg "class MessageBuffer" src
```

找某个函数：

```bash
rg "void wakeup|wakeup\\(" src/mem/ruby
```

找某个 debug flag：

```bash
rg "DPRINTF\\(RubySlicc" src build
```

找某个 SLICC transition：

```bash
rg "transition\\(" src/mem/ruby/protocol
```

找某个消息类型：

```bash
rg "GETX|GetX|GetM" src/mem/ruby/protocol
```

## 16. 修改 SLICC 后要重新编译

`.sm` 不是运行时脚本，改完需要重新生成 C++：

```bash
scons build/X86/gem5.opt -j$(nproc)
```

如果你怀疑生成代码没更新，可以看 build 目录下生成的协议文件，但一般不用直接改生成代码。

原则：

```text
改协议逻辑 -> 改 src/mem/ruby/protocol/*.sm
不要手改 build 目录里的 generated C++
```

## 17. 推荐的 Ruby 调试命令模板

模板一：先看协议 trace

```bash
build/X86/gem5.opt \
  --outdir=m5out/ruby_trace \
  --debug-flags=ProtocolTrace \
  --debug-file=protocol_trace.log \
  configs/example/se.py ...
```

模板二：看状态机和队列

```bash
build/X86/gem5.opt \
  --outdir=m5out/ruby_slicc \
  --debug-flags=RubySlicc,RubyQueue \
  --debug-start=1000000 \
  --debug-file=ruby_slicc.log \
  configs/example/se.py ...
```

模板三：GDB 抓崩溃

```bash
gdb --args build/X86/gem5.debug configs/example/se.py ...
```

进入 GDB 后：

```gdb
run
bt
```

## 18. 一个实用心法

调 gem5 不要只盯着一行代码。尤其是 Ruby：

```text
配置脚本决定拓扑
SLICC 决定协议行为
MessageBuffer 决定消息流
Ruby network 决定消息何时到达
stats/debug log 反映实际执行路径
```

所以一次完整排查通常是：

```text
现象 -> stats/config -> debug log -> SLICC transition -> C++/GDB
```

先把最小例子跑清楚，再扩大到复杂 workload。这样调起来会稳很多。

