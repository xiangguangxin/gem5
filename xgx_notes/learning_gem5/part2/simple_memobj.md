# Part 2 · 第 2 章：给 SimObject 加内存端口（SimpleMemobj）

> 对应源码：`src/learning_gem5/part2/simple_memobj.{hh,cc}` + `SimpleMemobj.py`
> 配置脚本：`configs/learning_gem5/part2/simple_memobj.py`

## 本章目标

写一个**插在 CPU 和内存之间**的 SimObject，理解 gem5 的**端口(port)**系统。
SimpleMemobj 本身不缓存任何东西，只是把请求和响应原样转发（pass-through）。

## 端口：内存事务的连接机制

本例通过端口传递内存请求与响应。SimObject 之间也可以通过参数引用、接口与方法调用协作；端口不是所有对象交互的唯一方式。
端口分两种角色：

| 端口类型 | 作用 | 方向 |
|----------|------|------|
| `RequestPort` | 发出请求（master 侧，主动方） | 出去 |
| `ResponsePort` | 接收请求（slave 侧，被动方） | 进来 |

**连接规则**：`RequestPort` 连 `ResponsePort`（请求方出口 → 响应方入口）。

## SimpleMemobj 的三个端口

```python
# SimpleMemobj.py
inst_port = ResponsePort("CPU side port, receives requests")   # 收 CPU 的取指请求
data_port = ResponsePort("CPU side port, receives requests")   # 收 CPU 的访存请求
mem_side  = RequestPort("Memory side port, sends requests")    # 向内存发请求
```

- 朝 CPU 的两个端口是 `ResponsePort`（被动收请求）；
- 朝内存的 `mem_side` 是 `RequestPort`（主动发请求）。

## C++ 实现要点

- 继承 `gem5::SimObject`（还不是 `ClockedObject`，所以没时钟）。
- **完全阻塞（fully blocking）**：同一时刻只有一个请求在处理，处理完一个才能处理下一个。
- 内部维护一个 `PacketPtr` 缓存当前请求，转发到 mem_side 后等待响应，再原样送回对应 CPU 端口。

## 配置拓扑

```python
# simple_memobj.py
system.cpu.icache_port = system.memobj.inst_port     # CPU 取指口 → memobj
system.cpu.dcache_port = system.memobj.data_port     # CPU 访存口 → memobj
system.memobj.mem_side = system.membus.cpu_side_ports # memobj → membus
```

```
CPU ──inst_port/data_port──► SimpleMemobj ──mem_side──► membus ──► DDR3
```

## 运行

```bash
# 在仓库根目录执行
build/X86/gem5.opt configs/learning_gem5/part2/simple_memobj.py
```

## 实际输出

```
Hello world!
Exiting @ tick 507962000 because exiting with last active thread context
```

以上为历史运行示例，具体 tick 随版本与配置变化。该对象不主动增加访问延迟，也不缓存数据；在相同配置与负载下应与直接连接的结果对照验证，不能仅凭历史时间相同推断所有负载下都等价。

## 分步实验 C3：请求、响应与 retry 的完整闭环

**重点逻辑：调用成功表示接收方接受了事务，不表示事务已经完成；拒绝请求后，要等资源就绪通知再重试。请求背压与响应背压是两条独立路径。**

### 步骤 1：运行并追踪一对事务

```bash
build/X86/gem5.opt --outdir=m5out/learning/c3_trace --debug-flags=SimpleMemobj --debug-file=ports.log configs/learning_gem5/part2/simple_memobj.py
rg -n 'Got request|Got response|retry' m5out/learning/c3_trace/ports.log
```

挑一个地址，在日志中找请求与响应。相同地址可能多次访问，仅凭地址不能唯一标识事务；本例串行处理时结合时间与顺序辨认。数据长度与命令需要时补充 DPRINTF 后重建。

### 步骤 2：按函数画正常路径

```text
CPUSidePort::recvTimingReq → handleRequest → MemSidePort::sendPacket
    → 下游接受并处理
MemSidePort::recvTimingResp → handleResponse → CPUSidePort::sendPacket
```

在源码里逐个找到上述函数，标出 `blocked` 何时置位、何时清除、如何凭 `isInstFetch()` 选择返回端口。注意响应转发前先释放资源，是为了允许同一调用链里上游再次发请求。

### 步骤 3：分开读三种等待

| 场景 | 包由谁保留 | 后续入口 |
|---|---|---|
| 对象忙，拒绝上游请求 | 上游发送者；本对象只记录需要通知重试 | `trySendRetry()` 通知上游 |
| 下游拒绝转发请求 | `MemSidePort::blockedPacket` | `recvReqRetry()` |
| 上游拒绝接收响应 | `CPUSidePort::blockedPacket` | `recvRespRetry()` |

对照源码验证此表。返回 false 的一方没有接收该包的所有权，不能同时把它当作已接受事务处理。`needRetry` 和 `blockedPacket` 不能混为同一种状态。

### 步骤 4：增加延迟练习

先画扩展状态：idle → holding → waiting_response → idle。新增 Latency 参数、事件和保存已接受请求的成员，在事件触发时调用原来的下游发送逻辑。`handleRequest()` 接受后保持 busy，不能先返回 false 再私下转发。

先取 0ns、10ns、100ns 三组。固定程序和内存配置，预期正延迟降低串行访问速度；同时检查正常退出和请求/响应匹配。计数仅在真正接受时增加，不能把重试次数当请求数。

**验收**：两张路径图、三类背压表、延迟实验。hello 未出现 retry 并不能证明 retry 正确；进一步使用可拒绝一次请求/响应的测试端点，验证拒绝 → 通知 → 重发 → 完成的日志链。未完成这项测试时，报告中注明覆盖不足。
