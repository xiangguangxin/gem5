# Part 2 · 第 3 章：自己写一个缓存（SimpleCache）

> 对应源码：`src/learning_gem5/part2/simple_cache.{hh,cc}` + `SimpleCache.py`
> 配置脚本：`configs/learning_gem5/part2/simple_cache.py`

## 本章目标

在 SimpleMemobj 的基础上写一个**真正的（但极简的）缓存**，重点引入：
**向量端口(VectorPort)**、**参数(Param)**、**时钟对象(ClockedObject)**、**统计(stats)**。

## SimpleCache 的特性（对照真实 Cache 做了简化）

- 全相联（fully-associative）
- 随机替换（random replacement）
- 写回（writeback）
- 完全阻塞（同一时刻只处理一个请求）

## 关键新概念 1：向量端口 VectorPort

```python
# SimpleCache.py
cpu_side = VectorResponsePort("CPU side port, receives requests")
mem_side = RequestPort("Memory side port, sends requests")
```

`cpu_side` 是一个**向量端口**：CPU 的取指口和数据口都连到它，gem5 会自动把它
拆成两个独立的端口实例（每个都对应一套 C++ 侧的 `CPUSidePort` 类）。

```python
# simple_cache.py —— 连两次，向量端口自动扩展
system.cpu.icache_port = system.cache.cpu_side
system.cpu.dcache_port = system.cache.cpu_side
```

## 关键新概念 2：Param 参数

```python
latency = Param.Cycles(1, "Cycles taken on a hit or to resolve a miss")
size    = Param.MemorySize("16KiB", "The size of the cache")
system  = Param.System(Parent.any, "The system this cache is part of")
```

- `Param.Cycles` / `Param.MemorySize`：带单位的类型（cycle / 字节），脚本里可写成 `size="1KiB"`。
- `Parent.any`：一个**代理(proxy)**，自动指向父节点所在的 `System`，免去手动连线。

## 关键新概念 3：ClockedObject 与统计

- SimpleCache 继承 `gem5::ClockedObject`（**有自己时钟**的 SimObject），
  用 `clockEdge()` 来模拟命中/缺失的 `latency` 个周期延迟。
- 通过 `statistics.hh` 里的 `statistics::Scalar` / `Histogram` 暴露统计量，
  模拟结束会写进 `m5out/stats.txt`（如命中数、缺失数、缺失率）。

## 配置拓扑

```python
system.cache = SimpleCache(size="1KiB")          # 只 1KiB，方便观察命中/缺失
system.cpu.icache_port = system.cache.cpu_side
system.cpu.dcache_port = system.cache.cpu_side
system.cache.mem_side  = system.membus.cpu_side_ports
```

```
CPU ──icache/dcache──► SimpleCache ──mem_side──► membus ──► DDR3
```

## 运行

```bash
# 在仓库根目录执行
build/X86/gem5.opt configs/learning_gem5/part2/simple_cache.py
```

## 实际输出

```
Hello world!
Exiting @ tick 53367000 because exiting with last active thread context
```

以上为历史输出，不作为验收的固定时间或加速比。当前统计字段为 `system.cache.hits` / `misses` / `missLatency` / `hitRatio`，具体以实际输出为准。

## 分步实验 C4：用日志连接命中、miss 与统计

**重点逻辑：命中由缓存本地返回；miss 可能把小访问扩成整块读，返回后填入缓存并满足原始请求。统计应与这个行为一致。**

### 步骤 1：运行并找到真实统计名

```bash
build/X86/gem5.opt --outdir=m5out/learning/c4_base --debug-flags=SimpleCache --debug-file=cache.log configs/learning_gem5/part2/simple_cache.py
rg -n '^system.cache\.' m5out/learning/c4_base/stats.txt
rg -n 'Hit|Miss|Upgrading|Inserting|Writing packet' m5out/learning/c4_base/cache.log
```

当前源码在 `SimpleCacheStats` 注册的是 `hits`、`misses`、`missLatency` 与 `hitRatio`，不是标准 Cache 的 `overallHits/overallMisses`。手工核对 `hitRatio = hits / (hits + misses)`；分母为零时不进行数值比较。

### 步骤 2：追踪一次 miss 返回

依次读 `handleRequest()`、`accessTiming()`、`handleResponse()`、`sendResponse()`。选一笔小于 cache line 的访问，记录原始 Packet 与整块 Packet 的作用，解释 `originalPacket` 为什么需要保存，何时才可释放相关数据。

随后选一笔 hit，解释为什么无需把该访问送到 DRAM。日志中的低级事件数不等于应用 load 数。

### 步骤 3：只改容量，再只改延迟

复制配置为同目录 `simple_cache_lab.py`，把 `SimpleCache(size="1KiB")` 改为 `SimpleCache(size="4KiB")`，输出到 `c4_size4`。再恢复 1KiB，设置 `latency=10`，输出到 `c4_latency10`。默认 latency 从 `SimpleCache.py` 核对。

两次只改一个变量。容量可能减少 miss，但随机替换与短负载可能让趋势不明显；延迟实验改变的是每次缓存访问决策的时序，不只命中路径。看 `clockEdge(latency)` 如何调用访问事件。

### 步骤 4：理解教学模型的局限

阅读 `insert()`，说明满缓存如何选牺牲块以及如何回送数据。不要直接套用标准 Cache 的 dirty-bit、MSHR 或协议能力。用与 Part 1 相同 workload 比较时，只能说明所选模型的结果，不能用一次 hello 加速比证明模型精度。

**验收**：一条 hit 路径、一条 miss 路径、三组统计和模型限制。下一步做设备时复用事件/端口/统计机制，不需要把该教学缓存扩成完整工业实现。
