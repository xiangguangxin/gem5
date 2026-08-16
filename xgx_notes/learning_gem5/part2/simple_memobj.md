# Part 2 · 第 2 章：给 SimObject 加内存端口（SimpleMemobj）

> 对应源码：`src/learning_gem5/part2/simple_memobj.{hh,cc}` + `SimpleMemobj.py`
> 配置脚本：`configs/learning_gem5/part2/simple_memobj.py`

## 本章目标

写一个**插在 CPU 和内存之间**的 SimObject，理解 gem5 的**端口(port)**系统。
SimpleMemobj 本身不缓存任何东西，只是把请求和响应原样转发（pass-through）。

## 端口：连接 SimObject 的唯一方式

在 gem5 里，SimObject 之间**不能直接互相调用**，只能通过「端口」连接。
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
cd /home/guangxinxiang.linux/github/gem5
build/X86/gem5.opt configs/learning_gem5/part2/simple_memobj.py
```

## 实际输出

```
Hello world!
Exiting @ tick 507962000 because exiting with last active thread context
```

**要点**：结束时刻 `507962000` 和 part1 的 `simple.py`（CPU 直连内存）**完全一样**，
因为它只是透传、没有任何缓存加速——正好印证了它是 pass-through。
