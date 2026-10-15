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

## 四个缓存特性分别是什么意思

这四个概念分别描述缓存的存放位置、淘汰策略、写入策略和并发能力。这里的“块”指 cache line，不是单个字节；例如容量 1KiB、块大小 64B 的缓存能容纳 16 个块。

### 1. 全相联：一个内存块可以放在任意缓存位置

假设缓存能容纳 4 个块，新来的 A 可以放入任意空闲位置，不受地址映射到某个固定组的限制：

```text
缓存：[空] [B] [空] [D]
A 可以使用第 0 或第 2 个位置
```

| 组织方式 | 一个内存块可以放在哪里 |
|---|---|
| 直接映射 | 地址决定的一个固定位置 |
| 组相联 | 地址决定的组内任意一路 |
| 全相联 | 整个缓存的任意位置，相当于只有一个组 |

当前 SimpleCache 使用 `cacheStore` 哈希表，以块地址为键查找数据。概念上它允许任意块占用缓存容量，但不能据此把软件哈希查找等同于真实硬件的全相联比较电路，也不能直接推导硬件面积和功耗。

### 2. 随机替换：满了以后随机选一个块淘汰

```text
已有：[A] [B] [C] [D]
装入 E，需要腾出空间
随机选中 B → 淘汰 B → 装入 E
结果：[A] [E] [C] [D]
```

它不按最近使用历史选择牺牲块；LRU 则选择最久未使用的块。全相联决定“允许放哪里”，替换策略决定“满了赶走谁”，两者是独立维度。

对应 `SimpleCache::insert()`：当 `cacheStore.size() >= capacity` 时，随机选择一个非空哈希桶，再随机选择桶内元素。这是教学实现的随机选块方法，不应理解成所有缓存块严格等概率被选中。

### 3. 写回：先修改缓存，淘汰时再向下游写出

以地址 X 的值为例：

```text
初始：         缓存 X=10，下游内存 X=10
CPU 写入 20：  缓存 X=20，下游内存 X=10
该块被淘汰时：把包含 X=20 的整个块写回下游
```

一般写回缓存用 dirty bit（脏位）记录块是否被修改，淘汰脏块时才需要写回。写直达（write-through）则在写缓存时也把写操作传给下游；是否在写缺失时分配缓存块，是另一个策略维度。

**当前 SimpleCache 没有逐块脏位：淘汰时总是构造 `MemCmd::WritebackDirty` 包，把整个块交给 `memPort.sendPacket()`，即使该块从未被 CPU 修改。** 因此理解一般写回机制时，要与这个教学简化区分。

### “下游”指什么：朝内存方向的下一层

下游是相对于当前缓存而言的，不一定直接是主存（memory）。例如：

```text
CPU → L1 Cache → L2 Cache → 内存系统
```

- 对 L1 来说，下游是 L2，L1 写回时先将数据交给 L2。
- 对 L2 来说，下游是内存系统，L2 写回时才向内存方向传递数据。

因此，L1 的写回不代表主存已经同步更新；最新数据可能仍保存在 L2 中。

当前 `configs/learning_gem5/part2/simple_cache.py` 的连接是：

```text
CPU → SimpleCache → SystemXBar（总线） → MemCtrl（内存控制器） → DRAM
```

这里 SimpleCache 的写回包通过 `memPort` 发出，经总线和内存控制器，最终更新 DRAM。总线负责转发事务，内存控制器负责安排内存访问，它们不是额外的一层缓存。

**写回不是“每次写缓存后马上再写内存”**：写命中时先修改缓存中的数据，通常等块被淘汰时再写给下游。在淘汰前，缓存和下游保存的值可以暂时不同；CPU 再次访问并命中时，使用缓存中的最新值。

写回请求发出不意味着数据已经立即完成下游更新；缓存里的最新数据也不会仅因仿真结束就自动全部写回。

### 4. 完全阻塞：当前请求占用处理资源时，拒绝新请求

**可以先理解成：这个缓存一次只处理一个 CPU 请求，处理期间，其他请求先等着。**

假设 CPU 先后发出两个请求：A 读取地址 `0x1000`，B 读取地址 `0x2000`。

```text
① 缓存接受 A，设置 blocked = true
② A 没命中，缓存向下游内存请求数据
③ 等待内存期间，B 到来
④ 缓存返回 false，拒绝接收 B；B 的包仍由上游保存
⑤ A 的数据回来，缓存准备返回响应，清除 blocked
⑥ 缓存通知上游重试 B，上游重新发送后才能开始处理 B
```

**即使 B 要的数据已经在缓存里，只要 A 还占着处理资源，B 也不能提前处理。** 这就是完全阻塞带来的限制：一个缺失请求会让后续本来可能命中的请求也等待。

这里不是把 gem5 整个程序暂停。调度器仍继续处理其他事件，内存仍能完成 A 的访问并送回响应；暂停的是这个缓存对新请求的接受。通知 retry 也不是缓存替 CPU 执行 B，而是告诉上游“可以重新尝试发送了”。

```text
接受 A → 等缓存访问延迟 → 缺失 → 等待下游响应 → 返回 A 的响应
                       ↑
                B 到来时若 blocked=true，则拒绝 B
```

`handleRequest()` 的关键逻辑是：

```cpp
if (blocked)
    return false;
blocked = true;
```

命中和缺失都会先占用这个资源；即使有多个 CPU 侧端口，它们也共享同一个 `blocked`。这与支持多个未完成缺失的非阻塞缓存不同，不能把向量端口数量当作并发事务容量。

拒绝后，请求包由上游保留，缓存通过 retry 通知上游重试。阻塞的是此对象接收新请求的能力，gem5 仍继续执行其他事件，才能让访问事件和内存响应到来。

当前 `sendResponse()` 会在尝试发送响应前清除 `blocked`，允许同一调用链中上游发出新请求。如果 CPU 暂时拒收响应，响应包由对应端口的 `blockedPacket` 保存，等待响应重试。因此 `blocked=false` 表示主要处理资源已释放，不保证此前响应已经被 CPU 接收，也不表示所有写回都已完成。

阅读时可用四个问题检查理解：**放哪里？满了淘汰谁？修改何时传到下游？忙时能否接受新请求？**

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
